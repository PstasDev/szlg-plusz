from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from .models import SchoolClass, StudentProfile, Tagozat, TeacherProfile, email_info

STUDENT_PROFILE_PROMPT_DISMISSED_KEY = "student_profile_prompt_dismissed_user"


def _student_profile_state(user):
    if user.is_group_mailbox:
        return None, {"tagozat": False, "om_id": False}, False

    try:
        profile = user.student_profile
    except StudentProfile.DoesNotExist:
        profile = None
    try:
        teacher_profile = user.teacher_profile
    except TeacherProfile.DoesNotExist:
        teacher_profile = None
    info = email_info(user.email)
    if not info.is_in_school_domain:
        return profile, {"tagozat": False, "om_id": False}, False
    is_student = bool(
        profile
        or (
            not teacher_profile
            and (info.is_student or info.is_part_time_student)
        )
    )
    missing = {
        "tagozat": is_student and (profile is None or profile.tagozat_id is None),
        "om_id": is_student and not (profile and (profile.om_id or "").strip()),
    }
    return profile, missing, is_student


def student_profile_needs_completion(user):
    _, missing, is_student = _student_profile_state(user)
    return is_student and any(missing.values())


def _safe_next_url(request, value):
    if isinstance(value, str) and value and url_has_allowed_host_and_scheme(
        value,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return value
    return reverse("dashboard")


def _render_completion(request, next_url, missing, *, values=None, errors=None, status=200):
    return render(
        request,
        "dashboard/student_profile_completion.html",
        {
            "section": "profile",
            "next_url": next_url,
            "missing_tagozat": missing["tagozat"],
            "missing_om_id": missing["om_id"],
            "tagozatok": Tagozat.objects.order_by("name"),
            "values": values or {},
            "errors": errors or {},
        },
        status=status,
    )


def _fill_inferred_class(profile, user):
    inferred = email_info(user.email).class_from_email
    if inferred is None:
        return []

    start_year, section = inferred
    current_section = (profile.szekcio or "").strip().upper()
    if (profile.kezdes_eve is not None and profile.kezdes_eve != start_year) or (
        current_section and current_section != section
    ):
        return []

    updated = []
    if profile.kezdes_eve is None:
        profile.kezdes_eve = start_year
        updated.append("kezdes_eve")
    if not current_section:
        profile.szekcio = section
        updated.append("szekcio")
    return updated


@login_required
@require_http_methods(["GET", "POST"])
def student_profile_completion(request):
    next_url = _safe_next_url(
        request,
        request.GET.get("next") if request.method == "GET" else request.POST.get("next"),
    )
    _, missing, is_student = _student_profile_state(request.user)
    if not is_student or not any(missing.values()):
        return redirect(next_url)

    values = {"tagozat": "", "om_id": ""}
    errors = {}
    if request.method == "POST":
        if request.POST.get("action") == "skip":
            request.session[STUDENT_PROFILE_PROMPT_DISMISSED_KEY] = str(request.user.pk)
            messages.info(request, "A hiányzó diákprofil-adatokat később is megadhatod.")
            return redirect(next_url)

        values = {
            "tagozat": request.POST.get("tagozat", "").strip(),
            "om_id": request.POST.get("om_id", "").strip(),
        }
        selected_tagozat = None
        if missing["tagozat"] and values["tagozat"]:
            selected_tagozat = Tagozat.objects.filter(slug=values["tagozat"]).first()
            if selected_tagozat is None:
                errors["tagozat"] = "Válassz egy érvényes tagozatot."
        if missing["om_id"] and len(values["om_id"]) > 32:
            errors["om_id"] = "Az OM azonosító legfeljebb 32 karakter lehet."

        has_value_to_save = bool(
            (missing["tagozat"] and selected_tagozat)
            or (missing["om_id"] and values["om_id"])
        )
        if not has_value_to_save and not errors:
            errors["non_field"] = "Adj meg legalább egy adatot, vagy válaszd a kihagyást."

        if not errors:
            with transaction.atomic():
                profile, _ = StudentProfile.objects.get_or_create(user=request.user)
                updated_fields = []
                if missing["tagozat"] and selected_tagozat and profile.tagozat_id is None:
                    profile.tagozat = selected_tagozat
                    updated_fields.append("tagozat")
                if missing["om_id"] and values["om_id"] and not (profile.om_id or "").strip():
                    profile.om_id = values["om_id"]
                    updated_fields.append("om_id")

                updated_fields.extend(_fill_inferred_class(profile, request.user))
                updated_fields = list(dict.fromkeys(updated_fields))
                if updated_fields:
                    profile.save(update_fields=updated_fields)

                section = (profile.szekcio or "").strip().upper()
                if profile.kezdes_eve is not None and section:
                    SchoolClass.objects.get_or_create(
                        start_year=profile.kezdes_eve,
                        section=section,
                    )

            request.session[STUDENT_PROFILE_PROMPT_DISMISSED_KEY] = str(request.user.pk)
            messages.success(request, "A diákprofil adatait elmentettük.")
            return redirect(next_url)

    return _render_completion(request, next_url, missing, values=values, errors=errors)
