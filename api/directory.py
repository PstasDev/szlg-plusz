"""Shared directory queries and stable identifiers for school groups."""

from dataclasses import dataclass
from urllib.parse import urlencode

from django.db.models import Q
from django.utils.text import slugify

from .models import (
    CustomUser,
    GroupMailboxAssociation,
    InstitutionalRole,
    ManualGroup,
    SchoolClass,
    StudentProfile,
    Tagozat,
    get_school_domain,
)


SMART_DIRECTORY_GROUPS = (
    ("student", "Diákok", "A diákprofil vagy az iskolai diák e-mail-cím alapján számított csoport."),
    ("teacher", "Tanárok", "TeacherProfile-lal rendelkező felhasználók."),
    ("part_time_student", "Esti tagozatos diákok", "Az esti tagozatos profil vagy e-mail-cím alapján számított csoport."),
    ("computer_test_account", "Számítógéptermi tesztfiókok", "Iskolai tesztfiókok; nem SZLG+ jogosultsági kör."),
    ("group_email", "Csoportos postafiókok", "Az adminisztrátor által csoportos postafiókként megjelölt fiókok."),
    (
        "teacher_or_school_employee",
        "Tanárok és iskolai munkatársak",
        "Az iskolai fiókformátum alapján számított csoport.",
    ),
)


@dataclass
class DirectoryGroup:
    key: str
    name: str
    type_label: str
    description: str
    members: object
    managers: object
    mailboxes: object
    is_public: bool = True
    manual_group: ManualGroup | None = None
    parent_name: str = ""

    @property
    def member_count(self):
        if isinstance(self.members, (list, tuple)):
            return len(self.members)
        return self.members.count()


def school_domain_suffix() -> str:
    """Return a safe e-mail suffix, including the @ separator, or an empty value."""
    configured = (get_school_domain() or "").strip().lower()
    if not configured:
        return ""
    if not configured.startswith("@"):
        configured = "@" + configured.lstrip("@")
    return configured


def people_queryset(viewer, query=""):
    """People visible to a viewer; staff/superusers can search every account."""
    users = CustomUser.objects.filter(is_active=True).select_related(
        "student_profile", "student_profile__tagozat", "teacher_profile"
    )
    if not (viewer.is_staff or viewer.is_superuser):
        suffix = school_domain_suffix()
        if not suffix:
            return users.none()
        users = users.filter(email__iendswith=suffix)

    query = (query or "").strip()
    if query:
        for term in query.split():
            users = users.filter(
                Q(first_name__icontains=term)
                | Q(last_name__icontains=term)
                | Q(email__icontains=term)
            )
    return users.order_by("is_group_mailbox", "last_name", "first_name", "email")


def visible_person(viewer, pk):
    return people_queryset(viewer).filter(pk=pk).first()


def ensure_school_classes():
    """Create class records for every class currently represented by a student profile."""
    suffix = school_domain_suffix()
    if not suffix:
        return
    classes = {
        (year, section.strip().upper())
        for year, section in StudentProfile.objects.filter(
            kezdes_eve__isnull=False,
            user__email__iendswith=suffix,
        ).exclude(szekcio="").values_list("kezdes_eve", "szekcio")
        if section and section.strip()
    }
    for year, section in classes:
        SchoolClass.objects.get_or_create(start_year=year, section=section)


def _mailboxes_for(key):
    return CustomUser.objects.filter(
        group_mailbox_associations__group_key=key,
        is_active=True,
    ).order_by("email")


def _ordered_users(queryset):
    return queryset.filter(is_active=True).order_by("last_name", "first_name", "email")


def _smart_group_members(key):
    users = CustomUser.objects.filter(is_active=True).select_related(
        "student_profile", "teacher_profile"
    )
    return [user for user in users if user.smart_groups.get(key, False)]


def _manual_directory_group(group):
    key = group.directory_key
    managers = group.managers.all()
    if group.created_by_id and not managers.filter(pk=group.created_by_id).exists():
        managers = list(managers) + [group.created_by]
    return DirectoryGroup(
        key=key,
        name=group.name,
        type_label="Kézi csoport",
        description=group.description,
        members=_ordered_users(CustomUser.objects.filter(manual_groups=group)),
        managers=managers,
        mailboxes=_mailboxes_for(key),
        is_public=group.is_public,
        manual_group=group,
        parent_name=group.parent.full_path if group.parent_id else "",
    )


def directory_groups(query="", *, browsable_only=False):
    """Return the unified directory view of calculated and manually managed groups."""
    ensure_school_classes()
    query = (query or "").strip()
    result = []
    school_suffix = school_domain_suffix()

    for key, name, description in SMART_DIRECTORY_GROUPS:
        result.append(
            DirectoryGroup(
                key=f"smart-{key}",
                name=name,
                type_label="Automatikus szerepcsoport",
                description=description,
                members=_smart_group_members(key),
                managers=(),
                mailboxes=_mailboxes_for(f"smart-{key}"),
            )
        )

    for tagozat in Tagozat.objects.all():
        key = f"tagozat-{tagozat.slug}"
        result.append(
            DirectoryGroup(
                key=key,
                name=tagozat.name,
                type_label="Tagozat",
                description="A tagozathoz rendelt diákok automatikus csoportja.",
                members=_ordered_users(
                    CustomUser.objects.filter(
                        student_profile__tagozat=tagozat,
                        email__iendswith=school_suffix,
                    ) if school_suffix else CustomUser.objects.none()
                ),
                managers=(),
                mailboxes=_mailboxes_for(key),
            )
        )

    sections = sorted(
        {
            section.strip().upper()
            for section in StudentProfile.objects.filter(
                user__email__iendswith=school_suffix
            ).exclude(szekcio="").values_list("szekcio", flat=True)
            if school_suffix
            if section and section.strip()
        },
        key=str.casefold,
    )
    for section in sections:
        key = f"szekcio-{slugify(section)}"
        result.append(
            DirectoryGroup(
                key=key,
                name=f"{section} szekció",
                type_label="Szekció",
                description="Az azonos szekcióba tartozó diákok automatikus csoportja.",
                members=_ordered_users(
                    CustomUser.objects.filter(
                        student_profile__szekcio__iexact=section,
                        email__iendswith=school_suffix,
                    )
                ),
                managers=(),
                mailboxes=_mailboxes_for(key),
            )
        )

    for school_class in SchoolClass.objects.select_related(
        "homeroom_teacher", "deputy_teacher"
    ):
        class_key = f"osztaly-{school_class.start_year}-{slugify(school_class.section)}"
        students_key = f"{class_key}-diakok"
        teachers = [
            teacher
            for teacher in (school_class.homeroom_teacher, school_class.deputy_teacher)
            if teacher
        ]
        result.extend(
            [
                DirectoryGroup(
                    key=students_key,
                    name=f"{school_class.name} diákjai",
                    type_label="Osztály · diákok",
                    description=f"A {school_class.name} osztályba tartozó diákok automatikus csoportja.",
                    members=_ordered_users(
                        CustomUser.objects.filter(
                            student_profile__kezdes_eve=school_class.start_year,
                            student_profile__szekcio__iexact=school_class.section,
                            email__iendswith=school_suffix,
                        )
                    ),
                    managers=teachers,
                    mailboxes=_mailboxes_for(students_key),
                ),
                DirectoryGroup(
                    key=f"{class_key}-osztalyfonok",
                    name=f"{school_class.name} osztályfőnöke",
                    type_label="Osztály · osztályfőnök",
                    description=f"A {school_class.name} osztály osztályfőnöke.",
                    members=(
                        [school_class.homeroom_teacher]
                        if school_class.homeroom_teacher_id
                        else []
                    ),
                    managers=teachers,
                    mailboxes=_mailboxes_for(
                        f"{class_key}-osztalyfonok"
                    ),
                ),
                DirectoryGroup(
                    key=f"{class_key}-helyettes",
                    name=f"{school_class.name} osztályfőnök-helyettese",
                    type_label="Osztály · osztályfőnök-helyettes",
                    description=f"A {school_class.name} osztály osztályfőnök-helyettese.",
                    members=(
                        [school_class.deputy_teacher]
                        if school_class.deputy_teacher_id
                        else []
                    ),
                    managers=teachers,
                    mailboxes=_mailboxes_for(
                        f"{class_key}-helyettes"
                    ),
                ),
            ]
        )

    for role in InstitutionalRole.objects.prefetch_related("members"):
        key = f"szerepkor-{role.slug}"
        result.append(
            DirectoryGroup(
                key=key,
                name=role.name,
                type_label="Iskolai szerepkör",
                description=role.description,
                members=_ordered_users(role.members.all()),
                managers=(),
                mailboxes=_mailboxes_for(key),
            )
        )

    manuals = ManualGroup.objects.select_related("parent", "created_by").prefetch_related(
        "managers"
    )
    if browsable_only and not query:
        manuals = manuals.filter(is_public=True)
    for group in manuals:
        result.append(_manual_directory_group(group))

    result.sort(key=lambda group: (group.name.casefold(), group.type_label.casefold()))
    if query:
        needle = query.casefold()
        result = [
            group
            for group in result
            if needle in group.name.casefold()
            or needle in group.description.casefold()
            or needle in group.key.casefold()
            or needle in group.parent_name.casefold()
        ]
    return result


def get_directory_group(key):
    return next(
        (group for group in directory_groups() if group.key == key),
        None,
    )


def group_choices():
    return [
        (group.key, f"{group.name} · {group.type_label}")
        for group in directory_groups()
    ]


def user_school_group_keys(user):
    """Stable group identifiers for application integrations; Django permission groups are excluded."""
    ensure_school_classes()
    keys = {
        f"smart-{key}"
        for key, enabled in user.smart_groups.items()
        if enabled and key != "staff"
    }
    for group in user.manual_groups.all():
        keys.update(
            f"manual-{ancestor.slug}"
            for ancestor in group.get_ancestors(include_self=True)
        )

    suffix = school_domain_suffix()
    student = (
        getattr(user, "student_profile", None)
        if suffix and user.email.lower().endswith(suffix)
        else None
    )
    if student:
        if student.tagozat_id:
            keys.add(f"tagozat-{student.tagozat.slug}")
        if student.szekcio:
            keys.add(f"szekcio-{slugify(student.szekcio.strip())}")
        if student.kezdes_eve and student.szekcio:
            school_class = SchoolClass.objects.filter(
                start_year=student.kezdes_eve,
                section__iexact=student.szekcio.strip(),
            ).first()
            if school_class:
                keys.add(
                    f"osztaly-{school_class.start_year}-"
                    f"{slugify(school_class.section)}-diakok"
                )

    for school_class in SchoolClass.objects.filter(
        Q(homeroom_teacher=user) | Q(deputy_teacher=user)
    ):
        if school_class.homeroom_teacher_id == user.pk:
            keys.add(
                f"osztaly-{school_class.start_year}-"
                f"{slugify(school_class.section)}-osztalyfonok"
            )
        if school_class.deputy_teacher_id == user.pk:
            keys.add(
                f"osztaly-{school_class.start_year}-"
                f"{slugify(school_class.section)}-helyettes"
            )

    keys.update(f"szerepkor-{slug}" for slug in user.institutional_roles.values_list("slug", flat=True))
    return sorted(keys)


def gmail_compose_url(emails):
    recipients = ",".join(sorted(set(emails)))
    if not recipients:
        return ""
    compose_url = "https://mail.google.com/mail/?" + urlencode(
        {"view": "cm", "fs": "1", "to": recipients}
    )
    # Avoid links that browsers or Gmail may truncate for very large rosters.
    return compose_url if len(compose_url) <= 6000 else ""


def mailbox_group_links(mailbox):
    links = GroupMailboxAssociation.objects.filter(mailbox=mailbox)
    by_key = {group.key: group for group in directory_groups()}
    return [by_key[link.group_key] for link in links if link.group_key in by_key]
