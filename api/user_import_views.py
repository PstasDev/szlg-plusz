"""Superuser-only, incremental import of user records from legacy databases."""

import json
from collections import Counter
from datetime import date
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from oauth2_provider.models import Application

from .models import (
    CustomUser,
    SchoolClass,
    StudentProfile,
    Tagozat,
    TeacherProfile,
    class_str_to_year_szekcio,
    email_info,
    get_school_domain,
)

MAX_IMPORT_RECORDS = 500
MAX_IMPORT_SOURCES = 20
MAX_IMPORT_BODY_BYTES = 1_000_000

ALLOWED_FIELDS = {
    "email",
    "last_name",
    "first_name",
    "phone",
    "date_of_birth",
    "osztaly",
    "kezdes_eve",
    "szekcio",
    "om_id",
    "tagozat",
    "employee_number",
    "is_student",
}

FIELD_LABELS = {
    "last_name": "Vezetéknév",
    "first_name": "Keresztnév",
    "phone": "Telefonszám",
    "date_of_birth": "Születési dátum",
    "kezdes_eve": "Osztály kezdésének éve",
    "szekcio": "Szekció",
    "om_id": "OM azonosító",
    "tagozat": "Tagozat",
    "employee_number": "Munkatársi azonosító",
}


def superuser_required(view_func):
    """Require a signed-in superuser; ordinary staff accounts get a 403."""

    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapped


class ImportInputError(ValueError):
    pass


def _json_body(request):
    if request.content_type != "application/json":
        raise ImportInputError("Az adatokat application/json formátumban küldd el.")
    body = request.body
    if len(body) > MAX_IMPORT_BODY_BYTES:
        raise ImportInputError("A JSON legfeljebb 1 MB lehet.")
    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ImportInputError("A beillesztett szöveg nem érvényes JSON.") from None


def _source_applications(source_ids):
    if not isinstance(source_ids, list) or not source_ids:
        raise ImportInputError("Válassz ki legalább egy forrásalkalmazást.")
    if len(source_ids) > MAX_IMPORT_SOURCES:
        raise ImportInputError(f"Legfeljebb {MAX_IMPORT_SOURCES} forrásalkalmazás választható.")
    if any(
        isinstance(source_id, bool)
        or not isinstance(source_id, int)
        or source_id < 1
        for source_id in source_ids
    ):
        raise ImportInputError("A forrásalkalmazások kiválasztása érvénytelen.")

    source_ids = list(dict.fromkeys(source_ids))
    applications = {
        application.pk: application
        for application in Application.objects.filter(pk__in=source_ids).only(
            "name", "client_id"
        )
    }
    missing = [source_id for source_id in source_ids if source_id not in applications]
    if missing:
        raise ImportInputError("Egy kiválasztott alkalmazás már nem érhető el; frissítsd az oldalt.")
    return [
        {
            "application_id": application.pk,
            "client_id": application.client_id,
            "name": application.name,
        }
        for application in (applications[source_id] for source_id in source_ids)
    ]


def _extract_batch(payload):
    if not isinstance(payload, dict) or set(payload) != {"users", "source_app_ids"}:
        raise ImportInputError("Az importcsomag „users” és „source_app_ids” mezőt tartalmazzon.")
    records = payload["users"]
    if not isinstance(records, list):
        raise ImportInputError("A felhasználói adatok legfelső szintje JSON-tömb legyen.")
    if not records:
        raise ImportInputError("A JSON-tömb legalább egy felhasználót tartalmazzon.")
    if len(records) > MAX_IMPORT_RECORDS:
        raise ImportInputError(f"Egy importban legfeljebb {MAX_IMPORT_RECORDS} felhasználó lehet.")
    return records, _source_applications(payload["source_app_ids"])


def _text_value(record, key, label, errors, *, max_length, uppercase=False):
    value = record.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        errors.append(f"A(z) „{label}” értéke szöveg legyen.")
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > max_length:
        errors.append(f"A(z) „{label}” legfeljebb {max_length} karakter lehet.")
        return None
    return value.upper() if uppercase else value


def _current_school_year():
    today = timezone.localdate()
    return today.year if today.month >= 9 else today.year - 1


def _parse_iso_date(value):
    try:
        return parse_date(value.strip())
    except ValueError:
        return None


def _parse_class(value):
    """Convert a class label (e.g. 2023F or 10. F) to its cohort and section."""
    compact_value = value.strip().upper().replace(" ", "").replace(".", "")
    try:
        year, section = class_str_to_year_szekcio(value)
    except (ValueError, IndexError):
        raise ValueError("Az osztály formátuma nem felismerhető.") from None

    section = section.strip().upper()
    if not section or len(section) > 10:
        raise ValueError("Az osztályhoz szekciót is adj meg, például „2023F”.")

    current_year = _current_school_year()
    if compact_value.startswith(("KNY", "NY")):
        # KNYA/NYE/NYF (or 0.A) denotes the class starting this school year.
        start_year = current_year
    elif year == 0 and compact_value.startswith("00"):
        start_year = 2000
    elif year == 0:
        start_year = current_year
    elif 9 <= year <= 12:
        # Accept a current grade such as 10.F as well as a four-digit cohort.
        extra_year = 1 if section in {"A", "E", "F"} else 0
        start_year = current_year - (year - 9 + extra_year)
    elif 0 <= year <= 99:
        # A short cohort such as 23F means 2023F; choose the nearest plausible century.
        candidates = [century + year for century in (1900, 2000, 2100)]
        plausible = [candidate for candidate in candidates if candidate <= current_year + 5]
        start_year = min(plausible, key=lambda candidate: abs(candidate - current_year))
    elif 1900 <= year <= current_year + 5:
        start_year = year
    else:
        raise ValueError("Az osztály évfolyama vagy kezdési éve nem érvényes.")

    if start_year < 1900 or start_year > current_year + 5:
        raise ValueError("Az osztály kezdési éve nem érvényes.")
    return start_year, section


def _tagozat_index(tagozatok=None):
    index = {}
    tagozatok = tagozatok if tagozatok is not None else Tagozat.objects.only("id", "name", "slug")
    for tagozat in tagozatok:
        for value in {tagozat.name.casefold(), tagozat.slug.casefold()}:
            index.setdefault(value, []).append(tagozat)
    return index


def _normalize_record(
    record,
    tagozat_index=None,
    school_domain=None,
    *,
    allow_unresolved_tagozat=False,
):
    if not isinstance(record, dict):
        return None, ["A rekordnak JSON-objektumnak kell lennie."]

    errors = []
    unknown = sorted(set(record) - ALLOWED_FIELDS)
    if unknown:
        errors.append("Ismeretlen mező(k): " + ", ".join(str(key) for key in unknown) + ".")

    email = record.get("email")
    if not isinstance(email, str) or not email.strip():
        errors.append("Az e-mail kötelező, és szövegként kell megadni.")
        email = None
    else:
        email = email.strip().lower()
        try:
            CustomUser._meta.get_field("email").clean(email, None)
        except ValidationError:
            errors.append("Az e-mail-cím formátuma nem érvényes.")
        if len(email) > 254:
            errors.append("Az e-mail-cím legfeljebb 254 karakter lehet.")

    normalized = {"email": email} if email else {}
    user_fields = (
        ("last_name", "Vezetéknév", 150),
        ("first_name", "Keresztnév", 150),
        ("phone", "Telefonszám", 32),
        ("om_id", "OM azonosító", 32),
        ("employee_number", "Munkatársi azonosító", 32),
    )
    for key, label, max_length in user_fields:
        value = _text_value(record, key, label, errors, max_length=max_length)
        if value:
            normalized[key] = value

    is_student = record.get("is_student")
    if is_student is not None:
        if not isinstance(is_student, bool):
            errors.append("Az „is_student” mező logikai érték legyen.")
        else:
            normalized["is_student"] = is_student

    birth_date = record.get("date_of_birth")
    if birth_date not in (None, ""):
        parsed_birth_date = (
            _parse_iso_date(birth_date) if isinstance(birth_date, str) else None
        )
        if parsed_birth_date is None:
            errors.append("A születési dátumot YYYY-MM-DD formában add meg.")
        else:
            normalized["date_of_birth"] = parsed_birth_date.isoformat()

    osztaly = _text_value(record, "osztaly", "Osztály", errors, max_length=40)
    raw_year = record.get("kezdes_eve")
    raw_section = record.get("szekcio")
    has_direct_class = raw_year not in (None, "") or raw_section not in (None, "")
    if osztaly and has_direct_class:
        errors.append("Az „osztaly” mező mellett ne add meg külön a „kezdes_eve” és „szekcio” mezőt.")
    elif osztaly:
        try:
            start_year, section = _parse_class(osztaly)
            normalized["kezdes_eve"] = start_year
            normalized["szekcio"] = section
        except ValueError as error:
            errors.append(str(error))
    elif has_direct_class:
        if raw_year in (None, "") or raw_section in (None, ""):
            errors.append("A „kezdes_eve” és „szekcio” mezőt együtt add meg.")
        else:
            start_year = None
            if isinstance(raw_year, bool) or not (
                isinstance(raw_year, int)
                or isinstance(raw_year, str)
                and raw_year.strip().isdigit()
            ):
                errors.append("A „kezdes_eve” pozitív egész évszám legyen.")
            else:
                start_year = int(raw_year)
                if start_year < 1900 or start_year > _current_school_year() + 5:
                    errors.append("A „kezdes_eve” nem érvényes évszám.")
            section = _text_value(
                {"szekcio": raw_section},
                "szekcio",
                "Szekció",
                errors,
                max_length=10,
                uppercase=True,
            )
            if start_year is not None and section:
                normalized["kezdes_eve"] = start_year
                normalized["szekcio"] = section

    if (
        not osztaly
        and not has_direct_class
        and email
        and is_student is not False
        and (is_student is True or not normalized.get("employee_number"))
    ):
        inferred_class = email_info(
            email,
            school_domain=school_domain,
        ).class_from_email
        if inferred_class:
            normalized["kezdes_eve"], normalized["szekcio"] = inferred_class

    tagozat_value = _text_value(
        record, "tagozat", "Tagozat", errors, max_length=120
    )
    if tagozat_value:
        if tagozat_index is None:
            tagozatok = list(
                Tagozat.objects.filter(
                    Q(slug__iexact=tagozat_value) | Q(name__iexact=tagozat_value)
                ).only("id", "name", "slug")[:2]
            )
        else:
            tagozatok = tagozat_index.get(tagozat_value.casefold(), [])[:2]
        if len(tagozatok) == 1:
            normalized["tagozat"] = tagozatok[0].slug
        elif allow_unresolved_tagozat:
            normalized["is_student"] = True
        elif tagozatok:
            errors.append(f"A(z) „{tagozat_value}” tagozatnév nem egyértelmű.")
        else:
            errors.append(f"Nem található ilyen tagozat: „{tagozat_value}”.")

    student_data = any(
        normalized.get(field)
        for field in ("kezdes_eve", "szekcio", "om_id", "tagozat")
    ) or bool(tagozat_value)
    if is_student is False and student_data:
        errors.append(
            "A rekordot nem diákként jelölted meg, de diákadat-mezőt is kitöltöttél. "
            "Jelöld diáknak, vagy töröld az osztály-, tagozat- és OM-adatokat."
        )

    if errors:
        return None, errors
    return normalized, []


def _preview_records(records, school_domain=None):
    prepared = []
    emails = []
    tagozatok = list(Tagozat.objects.only("id", "name", "slug"))
    tagozat_index = _tagozat_index(tagozatok)
    tagozat_by_slug = {tagozat.slug: tagozat for tagozat in tagozatok}
    school_domain = school_domain if school_domain is not None else get_school_domain()
    for index, record in enumerate(records, start=1):
        normalized, errors = _normalize_record(
            record,
            tagozat_index,
            school_domain,
            allow_unresolved_tagozat=True,
        )
        candidate_email = (
            record.get("email", "").strip().lower()
            if isinstance(record, dict) and isinstance(record.get("email"), str)
            else ""
        )
        has_explicit_class = isinstance(record, dict) and bool(
            (isinstance(record.get("osztaly"), str) and record["osztaly"].strip())
            or record.get("kezdes_eve") not in (None, "")
            or record.get("szekcio") not in (None, "")
        )
        email_record_info = (
            email_info(candidate_email, school_domain=school_domain)
            if candidate_email
            else None
        )
        email_class = email_record_info.class_from_email if email_record_info else None
        raw_student = record.get("is_student") if isinstance(record, dict) else None
        raw_employee_number = (
            record.get("employee_number") if isinstance(record, dict) else None
        )
        if isinstance(raw_employee_number, str):
            raw_employee_number = raw_employee_number.strip()
        explicit_student = isinstance(record, dict) and bool(
            raw_student is True
            or record.get("osztaly")
            or record.get("kezdes_eve") not in (None, "")
            or record.get("szekcio") not in (None, "")
            or record.get("om_id")
            or record.get("tagozat")
        )
        email_student = bool(
            email_record_info
            and (email_record_info.is_student or email_record_info.is_part_time_student)
        )
        student_hint = bool(
            explicit_student
            or (
                raw_student is not False
                and not raw_employee_number
                and email_student
            )
        )
        raw_tagozat = (
            record.get("tagozat", "").strip()
            if isinstance(record, dict) and isinstance(record.get("tagozat"), str)
            else ""
        )
        unresolved_tagozat = bool(
            normalized is not None and raw_tagozat and not normalized.get("tagozat")
        )
        prepared.append(
            {
                "index": index,
                "data": normalized,
                "errors": errors,
                "email": candidate_email,
                "class_inferred": bool(
                    email_class
                    and not has_explicit_class
                    and isinstance(record, dict)
                    and record.get("is_student") is not False
                    and (
                        record.get("is_student") is True
                        or not record.get("employee_number")
                    )
                    and student_hint
                ),
                "student_hint": student_hint,
                "unresolved_tagozat": unresolved_tagozat,
                "tagozat_warning": (
                    f"A(z) „{raw_tagozat}” tagozat nem azonosítható; válassz helyette tagozatot bulkban."
                    if unresolved_tagozat
                    else ""
                ),
            }
        )
        if candidate_email:
            emails.append(candidate_email)

    duplicate_emails = {
        email for email, count in Counter(emails).items() if count > 1
    }
    for row in prepared:
        if row["email"] in duplicate_emails:
            row["errors"].append("Ez az e-mail-cím többször szerepel az importban; egyik rekordot sem dolgozzuk fel.")
            row["data"] = None

    existing_users = {}
    existing_profiles = {}
    existing_teacher_profiles = set()
    valid_emails = [
        row["data"]["email"] for row in prepared if row["data"] is not None
    ]
    if valid_emails:
        matches = CustomUser.objects.annotate(email_key=Lower("email")).filter(
            email_key__in=valid_emails
        ).only("pk", "email", "first_name", "last_name")
        existing_users = {user.email.lower(): user for user in matches}
        existing_profiles = {
            profile.user_id: profile
            for profile in StudentProfile.objects.filter(
                user_id__in=[user.pk for user in existing_users.values()]
            ).select_related("tagozat")
        }
        existing_teacher_profiles = set(
            TeacherProfile.objects.filter(
                user_id__in=[user.pk for user in existing_users.values()]
            ).values_list("user_id", flat=True)
        )

    for row in prepared:
        data = row["data"]
        if data is None or not row["class_inferred"]:
            continue
        existing_user = existing_users.get(row["email"])
        teacher_profile = bool(
            existing_user and existing_user.pk in existing_teacher_profiles
        )
        original_record = records[row["index"] - 1]
        explicitly_student = isinstance(original_record, dict) and bool(
            original_record.get("is_student") is True
            or original_record.get("osztaly")
            or original_record.get("kezdes_eve") not in (None, "")
            or original_record.get("szekcio") not in (None, "")
            or original_record.get("om_id")
            or original_record.get("tagozat")
        )
        if teacher_profile and not explicitly_student:
            data.pop("kezdes_eve", None)
            data.pop("szekcio", None)
            data["is_student"] = False
            row["class_inferred"] = False

    rows = []
    counts = {"new": 0, "existing": 0, "invalid": 0}
    for row in prepared:
        data = row["data"]
        if data is None:
            status = "invalid"
            email = row["email"]
            display_name = ""
            class_label = ""
            tagozat_label = ""
            needs_tagozat = False
            is_student = row["student_hint"]
            has_student_profile = False
            warnings = [row["tagozat_warning"]] if row["tagozat_warning"] else []
            counts["invalid"] += 1
        else:
            email = data["email"]
            existing_user = existing_users.get(email)
            status = "existing" if existing_user else "new"
            display_name = " ".join(
                part for part in (data.get("last_name", ""), data.get("first_name", "")) if part
            )
            if existing_user:
                counts["existing"] += 1
                display_name = existing_user.get_full_name() or display_name
            else:
                counts["new"] += 1
            profile = existing_profiles.get(existing_user.pk) if existing_user else None
            has_student_profile = profile is not None
            profile_tagozat = profile.tagozat if profile and profile.tagozat_id else None
            record_tagozat = tagozat_by_slug.get(data.get("tagozat"))
            known_tagozat = profile_tagozat or record_tagozat
            tagozat_label = known_tagozat.name if known_tagozat else ""

            class_year = data.get("kezdes_eve")
            class_section = data.get("szekcio")
            if class_year is None and profile:
                class_year = profile.kezdes_eve
            if not class_section and profile:
                class_section = profile.szekcio
            if class_year is not None and class_section:
                class_label = f"{class_year}{class_section}"

            email_info_for_row = email_info(email, school_domain=school_domain)
            teacher_profile = bool(
                existing_user and existing_user.pk in existing_teacher_profiles
            )
            is_student = bool(
                data.get("is_student") is True
                or data.get("om_id")
                or data.get("kezdes_eve") is not None
                or data.get("tagozat")
                or profile
                or (
                    data.get("is_student") is not False
                    and not data.get("employee_number")
                    and not teacher_profile
                    and (
                        email_info_for_row.is_student
                        or email_info_for_row.is_part_time_student
                    )
                )
            )
            needs_tagozat = is_student and known_tagozat is None
            warnings = [row["tagozat_warning"]] if row["tagozat_warning"] else []
        rows.append(
            {
                "index": row["index"],
                "email": email,
                "display_name": display_name,
                "class_label": class_label,
                "class_inferred": row["class_inferred"],
                "is_student": is_student,
                "has_student_profile": has_student_profile,
                "tagozat_label": tagozat_label,
                "needs_tagozat": needs_tagozat,
                "warnings": warnings,
                "status": status,
                "errors": row["errors"],
                "data": data,
            }
        )
    return rows, counts


def _profile_for(user, related_name, model):
    try:
        return getattr(user, related_name), False
    except model.DoesNotExist:
        return model(user=user), True


def _apply_import_record(data, source_apps):
    """Create an account or fill only currently blank fields on an existing one."""
    with transaction.atomic():
        user = (
            CustomUser.objects.select_for_update()
            .filter(email__iexact=data["email"])
            .first()
        )
        created = user is None
        if created:
            # No password is imported or guessed. Django stores an unusable password.
            user = CustomUser.objects.create_user(email=data["email"])

        added = []
        preserved = []
        warnings = []
        source_apps_added = []
        user_updates = []
        for field in ("last_name", "first_name", "phone"):
            value = data.get(field)
            if not value:
                continue
            current = getattr(user, field)
            if not (current or "").strip():
                setattr(user, field, value)
                user_updates.append(field)
                added.append(FIELD_LABELS[field])
            else:
                preserved.append(FIELD_LABELS[field])

        birth_date = data.get("date_of_birth")
        if birth_date:
            if user.date_of_birth is None:
                user.date_of_birth = date.fromisoformat(birth_date)
                user_updates.append("date_of_birth")
                added.append(FIELD_LABELS["date_of_birth"])
            else:
                preserved.append(FIELD_LABELS["date_of_birth"])

        import_sources = user.import_sources
        if isinstance(import_sources, list):
            import_sources = list(import_sources)
        elif import_sources is None:
            import_sources = []
        else:
            import_sources = [import_sources]
        known_source_ids = {
            source.get("client_id")
            for source in import_sources
            if isinstance(source, dict)
        }
        for source in source_apps:
            if source["client_id"] in known_source_ids:
                continue
            import_sources.append(source)
            known_source_ids.add(source["client_id"])
            source_apps_added.append(source["name"])
        if source_apps_added:
            user.import_sources = import_sources
            user_updates.append("import_sources")
            added.append("Importforrás")

        if user_updates:
            user.save(update_fields=user_updates)

        has_student_data = data.get("is_student") is True or any(
            data.get(field)
            for field in ("kezdes_eve", "szekcio", "om_id", "tagozat")
        )
        if has_student_data:
            profile, profile_created = _profile_for(
                user, "student_profile", StudentProfile
            )
            profile_updates = []
            for field in ("om_id", "tagozat"):
                value = data.get(field)
                if not value:
                    continue
                current = getattr(profile, field)
                if field == "tagozat":
                    current_value = current.slug if current else ""
                else:
                    current_value = (current or "").strip()
                if not current_value:
                    if field == "tagozat":
                        profile.tagozat = Tagozat.objects.get(slug__iexact=value)
                    else:
                        setattr(profile, field, value)
                    profile_updates.append(field)
                    added.append(FIELD_LABELS[field])
                else:
                    preserved.append(FIELD_LABELS[field])

            incoming_year = data.get("kezdes_eve")
            incoming_section = data.get("szekcio")
            if incoming_year is not None and incoming_section:
                current_year = profile.kezdes_eve
                current_section = (profile.szekcio or "").strip().upper()
                class_conflict = (
                    current_year is not None and current_year != incoming_year
                ) or (current_section and current_section != incoming_section)
                if class_conflict:
                    preserved.extend((FIELD_LABELS["kezdes_eve"], FIELD_LABELS["szekcio"]))
                    warnings.append("A meglévő osztályadat eltér; ezért azt nem módosítottuk.")
                else:
                    if current_year is None:
                        profile.kezdes_eve = incoming_year
                        profile_updates.append("kezdes_eve")
                        added.append(FIELD_LABELS["kezdes_eve"])
                    else:
                        preserved.append(FIELD_LABELS["kezdes_eve"])
                    if not current_section:
                        profile.szekcio = incoming_section
                        profile_updates.append("szekcio")
                        added.append(FIELD_LABELS["szekcio"])
                    else:
                        preserved.append(FIELD_LABELS["szekcio"])

            if profile_created:
                profile.save()
            elif profile_updates:
                profile.save(update_fields=profile_updates)
            final_section = (profile.szekcio or "").strip().upper()
            if profile.kezdes_eve is not None and final_section:
                SchoolClass.objects.get_or_create(
                    start_year=profile.kezdes_eve,
                    section=final_section,
                )

        employee_number = data.get("employee_number")
        force_teacher_profile = (
            data.get("is_student") is False
            and not user.is_group_mailbox
            and email_info(user.email).class_from_email is not None
        )
        if force_teacher_profile:
            try:
                user.student_profile
            except StudentProfile.DoesNotExist:
                pass
            else:
                force_teacher_profile = False

        if employee_number or force_teacher_profile:
            profile, profile_created = _profile_for(
                user, "teacher_profile", TeacherProfile
            )
            if employee_number and not (profile.employee_number or "").strip():
                profile.employee_number = employee_number
                if profile_created:
                    profile.save()
                else:
                    profile.save(update_fields=["employee_number"])
                added.append(FIELD_LABELS["employee_number"])
            elif profile_created:
                profile.save()
                added.append("Tanári profil")
            else:
                if employee_number:
                    preserved.append(FIELD_LABELS["employee_number"])

        if created:
            status = "created"
            message = "Új fiókot hoztunk létre."
        elif added:
            status = "updated"
            message = "A hiányzó adatokat kiegészítettük."
        else:
            status = "unchanged"
            message = "Nem volt hiányzó adat; a meglévő fiókot változatlanul hagytuk."

        return {
            "status": status,
            "email": user.email,
            "message": message,
            "added": added,
            "preserved": list(dict.fromkeys(preserved)),
            "warnings": warnings,
            "sources_added": source_apps_added,
        }


@superuser_required
@never_cache
@require_GET
def user_import_page(request):
    response = render(
        request,
        "dashboard/user_import.html",
        {
            "section": "user-import",
            "applications": Application.objects.order_by("name").only(
                "name", "client_id"
            ),
            "tagozatok": Tagozat.objects.order_by("name"),
            "max_import_records": MAX_IMPORT_RECORDS,
            "max_import_sources": MAX_IMPORT_SOURCES,
        },
    )
    response["Cache-Control"] = "no-store"
    return response


@superuser_required
@never_cache
@require_POST
def user_import_preview(request):
    try:
        records, source_apps = _extract_batch(_json_body(request))
    except ImportInputError as error:
        return JsonResponse({"error": str(error)}, status=400)
    rows, counts = _preview_records(records, get_school_domain())
    response = JsonResponse(
        {
            "rows": rows,
            "counts": counts,
            "source_apps": [source["name"] for source in source_apps],
        }
    )
    response["Cache-Control"] = "no-store"
    return response


@superuser_required
@never_cache
@require_POST
def user_import_one(request):
    try:
        payload = _json_body(request)
        if not isinstance(payload, dict) or set(payload) != {"user", "source_app_ids"}:
            raise ImportInputError("Egy rekordot és a forrásalkalmazásokat add meg.")
        source_apps = _source_applications(payload["source_app_ids"])
    except ImportInputError as error:
        return JsonResponse({"error": str(error)}, status=400)
    normalized, errors = _normalize_record(payload["user"])
    if errors:
        return JsonResponse({"error": "A rekord ellenőrzése nem sikerült.", "details": errors}, status=400)

    try:
        result = _apply_import_record(normalized, source_apps)
    except IntegrityError:
        # A unique e-mail constraint can win a race with another import request.
        # Retry once against the newly existing account and keep the same fill-only rule.
        try:
            result = _apply_import_record(normalized, source_apps)
        except IntegrityError:
            return JsonResponse(
                {"error": "Az adatbázis nem tudta biztonságosan menteni ezt a rekordot. Próbáld újra."},
                status=409,
            )
    response = JsonResponse(result)
    response["Cache-Control"] = "no-store"
    return response
