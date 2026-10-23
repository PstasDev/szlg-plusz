from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django_ratelimit.decorators import ratelimit
from oauth2_provider.generators import generate_client_secret
from oauth2_provider.models import (
    AccessToken,
    Application,
    Grant,
    IDToken,
    RefreshToken,
)

from .access import can_access_school_features
from .directory import (
    directory_groups,
    ensure_school_classes,
    get_directory_group,
    gmail_compose_url,
    mailbox_group_links,
    people_queryset,
    user_school_group_keys,
    visible_person,
)
from .forms import (
    ApplicationForm,
    GroupMailboxAssociationForm,
    GroupMailboxFlagForm,
    InstitutionalRoleForm,
    ManualGroupForm,
    SchoolClassCreateForm,
    SchoolClassForm,
)
from .models import (
    CustomUser,
    GroupMailboxAssociation,
    InstitutionalRole,
    ManualGroup,
    Passkey,
    SchoolClass,
    UserAppConnection,
)
from .scopes import describe_scopes

MAX_APPLICATIONS_PER_USER = 10


def _own_application(request, pk):
    return get_object_or_404(
        Application.objects.select_related("profile"), pk=pk, user=request.user
    )


@login_required
@require_GET
def dashboard(request):
    launcher_apps = (
        UserAppConnection.objects.filter(
            user=request.user,
            application__profile__launch_url__gt="",
        )
        .select_related("application", "application__profile")
        .order_by("application__name")
    )
    school_access = can_access_school_features(request.user)
    query = request.GET.get("q", "").strip() if school_access else ""
    people = people_queryset(request.user, query) if school_access and len(query) >= 2 else []
    if hasattr(people, "filter"):
        school_people = people.filter(is_group_mailbox=False)
        group_mailboxes = people.filter(is_group_mailbox=True)
    else:
        school_people = []
        group_mailboxes = []
    return render(
        request,
        "dashboard/home.html",
        {
            "section": "home",
            "launcher_apps": launcher_apps,
            "query": query,
            "school_people": school_people,
            "group_mailboxes": group_mailboxes,
            "has_searched": len(query) >= 2,
        },
    )


@login_required
@require_GET
def directory_person(request, pk):
    if not can_access_school_features(request.user):
        return HttpResponseForbidden("Az iskolai címtár csak iskolai fiókkal érhető el.")
    person = visible_person(request.user, pk)
    if person is None:
        from django.http import Http404

        raise Http404
    student_profile = getattr(person, "student_profile", None)
    person_group_keys = set(user_school_group_keys(person))
    groups = [group for group in directory_groups() if group.key in person_group_keys]
    mailbox_groups = mailbox_group_links(person) if person.is_group_mailbox else []
    return render(
        request,
        "dashboard/person_detail.html",
        {
            "section": "home",
            "person": person,
            "student_profile": student_profile,
            "groups": groups,
            "mailbox_groups": mailbox_groups,
            "group_count": len(groups) + len(mailbox_groups),
        },
    )


@login_required
@require_GET
def groups(request):
    if not can_access_school_features(request.user):
        return HttpResponseForbidden("Az iskolai csoportok csak iskolai fiókkal érhetők el.")
    query = request.GET.get("q", "").strip()
    ensure_school_classes()
    groups_list = directory_groups(query, browsable_only=not bool(query))
    my_manual_groups = ManualGroup.objects.filter(
        Q(members=request.user) | Q(managers=request.user) | Q(created_by=request.user)
    ).distinct().select_related("parent")
    return render(
        request,
        "dashboard/groups.html",
        {
            "section": "groups",
            "groups": groups_list,
            "query": query,
            "my_manual_groups": my_manual_groups,
            "can_manage_directory": request.user.is_staff or request.user.is_superuser,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
@ratelimit(key="user", rate="10/h", method="POST", block=True)
def group_new(request):
    if not can_access_school_features(request.user):
        return HttpResponseForbidden("Iskolai csoportot csak iskolai fiókkal lehet kezelni.")
    form = ManualGroupForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            group = form.save(commit=False)
            group.created_by = request.user
            group.save()
            form.save_m2m()
            group.managers.add(request.user)
            group.members.set(form.cleaned_data.get("members", []))
            group.managers.add(*form.cleaned_data.get("managers", []))
        messages.success(request, "A csoportot létrehoztuk. Az önálló csatlakozás nem engedélyezett.")
        return redirect("group-detail", group_key=group.directory_key)
    return render(
        request,
        "dashboard/group_form.html",
        {"section": "groups", "form": form, "editing": False},
    )


@login_required
@require_http_methods(["GET", "POST"])
@ratelimit(key="user", rate="30/h", method="POST", block=True)
def group_detail(request, group_key):
    if not can_access_school_features(request.user):
        return HttpResponseForbidden("Az iskolai csoportok csak iskolai fiókkal érhetők el.")
    directory_group = get_directory_group(group_key)
    if directory_group is None:
        from django.http import Http404

        raise Http404
    manual_group = directory_group.manual_group
    can_manage = bool(
        manual_group
        and (
            request.user.is_staff
            or request.user.is_superuser
            or manual_group.created_by_id == request.user.pk
            or manual_group.managers.filter(pk=request.user.pk).exists()
        )
    )
    form = None
    if request.method == "POST":
        if not can_manage:
            return HttpResponseForbidden("Ezt a csoportot csak a kezelői módosíthatják.")
        form = ManualGroupForm(request.POST, instance=manual_group, user=request.user)
        if form.is_valid():
            with transaction.atomic():
                manual_group = form.save(commit=False)
                manual_group.save()
                form.save_m2m()
                manual_group.members.set(form.cleaned_data.get("members", []))
                manual_group.managers.set(form.cleaned_data.get("managers", []))
                if not (request.user.is_staff or request.user.is_superuser):
                    manual_group.managers.add(request.user)
            messages.success(request, "A csoport adatait és tagságát elmentettük.")
            return redirect("group-detail", group_key=manual_group.directory_key)
    elif can_manage:
        form = ManualGroupForm(instance=manual_group, user=request.user)

    # Re-fetch after edits and attach all current mailbox mappings.
    directory_group = get_directory_group(group_key)
    emails = [member.email for member in directory_group.members]
    return render(
        request,
        "dashboard/group_detail.html",
        {
            "section": "groups",
            "group": directory_group,
            "form": form,
            "can_manage": can_manage,
            "gmail_url": gmail_compose_url(emails),
            "recipients": ", ".join(sorted(set(emails))),
            "manager_count": len(directory_group.managers)
            if isinstance(directory_group.managers, (list, tuple))
            else directory_group.managers.count(),
        },
    )


def _require_directory_admin(request):
    return request.user.is_staff or request.user.is_superuser


@login_required
@require_http_methods(["GET", "POST"])
def directory_setup(request):
    if not _require_directory_admin(request):
        return HttpResponseForbidden("A címtár beállítását csak staff vagy admin végezheti.")
    ensure_school_classes()
    visible_users = people_queryset(request.user).filter(is_group_mailbox=False)
    role_form = InstitutionalRoleForm(user_queryset=visible_users)
    class_form = SchoolClassCreateForm()
    mailbox_form = GroupMailboxAssociationForm()
    mailbox_flag_form = GroupMailboxFlagForm()
    error_form = None

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create-role":
            error_form = InstitutionalRoleForm(
                request.POST, user_queryset=visible_users
            )
            if error_form.is_valid():
                error_form.save()
                messages.success(request, "Az iskolai szerepkört elmentettük.")
                return redirect("directory-setup")
        elif action == "create-class":
            class_form = SchoolClassCreateForm(request.POST)
            if class_form.is_valid():
                class_form.save()
                messages.success(request, "Az osztályt rögzítettük.")
                return redirect("directory-setup")
        elif action == "assign-class":
            school_class = get_object_or_404(SchoolClass, pk=request.POST.get("class_id"))
            assignment_form = SchoolClassForm(request.POST, instance=school_class)
            if assignment_form.is_valid():
                assignment_form.save()
                messages.success(request, f"A(z) {school_class.name} osztály szerepköreit elmentettük.")
                return redirect("directory-setup")
            messages.error(request, "Ellenőrizd az osztály szerepköreinek adatait.")
        elif action == "assign-role":
            role = get_object_or_404(InstitutionalRole, pk=request.POST.get("role_id"))
            role_form = InstitutionalRoleForm(
                request.POST, instance=role, user_queryset=visible_users
            )
            if role_form.is_valid():
                role_form.save()
                messages.success(request, f"A(z) {role.name} szerepkör betöltőit elmentettük.")
                return redirect("directory-setup")
            error_form = role_form
        elif action == "link-mailbox":
            mailbox_form = GroupMailboxAssociationForm(request.POST)
            if mailbox_form.is_valid():
                mailbox_form.save()
                messages.success(request, "A csoportos postafiókot összekapcsoltuk a csoporttal.")
                return redirect("directory-setup")
        elif action == "mark-mailbox":
            mailbox_flag_form = GroupMailboxFlagForm(request.POST)
            if mailbox_flag_form.is_valid():
                mailbox = mailbox_flag_form.cleaned_data["mailbox"]
                mailbox.is_group_mailbox = True
                mailbox.save(update_fields=["is_group_mailbox"])
                messages.success(request, f"A(z) {mailbox.email} fiókot csoportos postafióknak jelöltük.")
                return redirect("directory-setup")
        elif action == "unlink-mailbox":
            get_object_or_404(GroupMailboxAssociation, pk=request.POST.get("link_id")).delete()
            messages.success(request, "A postafiók-csoport kapcsolatot töröltük.")
            return redirect("directory-setup")
        elif action == "unmark-mailbox":
            mailbox = get_object_or_404(
                CustomUser.objects.filter(is_group_mailbox=True),
                pk=request.POST.get("mailbox_id"),
            )
            if mailbox.group_mailbox_associations.exists():
                messages.error(request, "Előbb töröld a postafiók csoportkapcsolatait.")
            else:
                mailbox.is_group_mailbox = False
                mailbox.save(update_fields=["is_group_mailbox"])
                messages.success(request, f"A(z) {mailbox.email} fiókot visszaállítottuk személyes fiókként.")
                return redirect("directory-setup")

    school_classes = [
        (school_class, SchoolClassForm(instance=school_class))
        for school_class in SchoolClass.objects.select_related(
            "homeroom_teacher", "deputy_teacher"
        )
    ]
    role_forms = [
        (role, InstitutionalRoleForm(instance=role, user_queryset=visible_users))
        for role in InstitutionalRole.objects.prefetch_related("members")
    ]
    required_roles_missing = InstitutionalRole.objects.filter(
        is_required=True, members__isnull=True
    ).distinct()
    incomplete_classes = [
        school_class
        for school_class in SchoolClass.objects.all()
        if not school_class.homeroom_teacher_id or not school_class.deputy_teacher_id
    ]
    linked_mailbox_ids = GroupMailboxAssociation.objects.values_list(
        "mailbox_id", flat=True
    )
    unlinked_mailboxes = CustomUser.objects.filter(
        is_active=True, is_group_mailbox=True
    ).exclude(pk__in=linked_mailbox_ids)
    mailbox_links = GroupMailboxAssociation.objects.select_related("mailbox")
    group_by_key = {group.key: group for group in directory_groups()}
    mailbox_links = [
        (link, group_by_key.get(link.group_key)) for link in mailbox_links
    ]
    task_count = (
        required_roles_missing.count()
        + len(incomplete_classes)
        + unlinked_mailboxes.count()
    )
    return render(
        request,
        "dashboard/directory_setup.html",
        {
            "section": "directory-setup",
            "role_form": error_form or role_form,
            "class_form": class_form,
            "mailbox_form": mailbox_form,
            "mailbox_flag_form": mailbox_flag_form,
            "school_classes": school_classes,
            "role_forms": role_forms,
            "required_roles_missing": required_roles_missing,
            "incomplete_classes": incomplete_classes,
            "unlinked_mailboxes": unlinked_mailboxes,
            "group_mailboxes": CustomUser.objects.filter(
                is_active=True, is_group_mailbox=True
            ).order_by("email"),
            "mailbox_links": mailbox_links,
            "task_count": task_count,
        },
    )


@login_required
@require_GET
def profile(request):
    user = request.user
    school_groups = []
    if can_access_school_features(user):
        user_group_keys = set(user_school_group_keys(user))
        school_groups = [
            group for group in directory_groups() if group.key in user_group_keys
        ]
    return render(
        request,
        "dashboard/profile.html",
        {
            "section": "profile",
            "student_profile": getattr(user, "student_profile", None),
            "teacher_profile": getattr(user, "teacher_profile", None),
            "school_groups": school_groups,
            "permission_groups": user.groups.all(),
            "has_password": user.has_usable_password(),
            "passkey_count": Passkey.objects.filter(user=user).count(),
            "grant_count": len(_active_grants(user)),
            "application_count": Application.objects.filter(user=user).count(),
        },
    )


@login_required
@require_GET
def dashboard_placeholder(request, title, description):
    if (
        request.resolver_match.url_name in {"schedule", "map"}
        and not can_access_school_features(request.user)
    ):
        return HttpResponseForbidden("Ez az iskolai szolgáltatás csak iskolai fiókkal érhető el.")
    return render(
        request,
        "dashboard/placeholder.html",
        {
            "section": request.resolver_match.url_name,
            "page_title": title,
            "page_description": description,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
@ratelimit(key="user", rate="10/m", method="POST", block=True)
def security(request):
    user = request.user
    has_password = user.has_usable_password()
    form_class = PasswordChangeForm if has_password else SetPasswordForm

    if request.method == "POST":
        form = form_class(user, request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, form.user)
            messages.success(
                request,
                "A jelszavadat megváltoztattuk." if has_password else "A jelszavadat beállítottuk.",
            )
            return redirect("security")
    else:
        form = form_class(user)

    return render(
        request,
        "dashboard/security.html",
        {
            "section": "security",
            "form": form,
            "has_password": has_password,
            "passkeys": Passkey.objects.filter(user=user),
        },
    )


@login_required
def applications(request):
    return render(
        request,
        "dashboard/applications.html",
        {
            "section": "applications",
            "applications": Application.objects.filter(user=request.user).select_related("profile"),
            "limit_reached": _application_limit_reached(request.user),
        },
    )


def _application_limit_reached(user) -> bool:
    if user.is_staff:
        return False
    return Application.objects.filter(user=user).count() >= MAX_APPLICATIONS_PER_USER


def _render_application(request, application, new_secret=None, status=200):
    group_names = (
        {group.key: group.name for group in directory_groups()}
        if can_access_school_features(request.user)
        else {}
    )
    required_group_names = [
        group_names[key]
        for key in getattr(getattr(application, "profile", None), "required_group_keys", [])
        if key in group_names
    ]
    return render(
        request,
        "dashboard/application_detail.html",
        {
            "section": "applications",
            "application": application,
            "redirect_uris": application.redirect_uris.split(),
            "new_secret": new_secret,
            "required_group_names": required_group_names,
        },
        status=status,
    )


@login_required
@require_http_methods(["GET", "POST"])
@ratelimit(key="user", rate="20/h", method="POST", block=True)
def application_new(request):
    if _application_limit_reached(request.user):
        messages.error(
            request,
            f"Legfeljebb {MAX_APPLICATIONS_PER_USER} alkalmazást regisztrálhatsz. "
            "Törölj egyet, mielőtt újat hoznál létre.",
        )
        return redirect("applications")

    if request.method == "POST":
        form = ApplicationForm(request.POST, request.FILES, user=request.user)
        # The model generates the secret on instantiation; it is hashed on save.
        new_secret = form.instance.client_secret
        if form.is_valid():
            with transaction.atomic():
                application = form.save()
            show_secret = new_secret if application.client_type == Application.CLIENT_CONFIDENTIAL else None
            messages.success(request, "Az alkalmazást regisztráltuk.")
            return _render_application(request, application, new_secret=show_secret)
    else:
        form = ApplicationForm(user=request.user)

    return render(
        request,
        "dashboard/application_form.html",
        {"section": "applications", "form": form, "editing": False},
    )


@login_required
def application_detail(request, pk):
    return _render_application(request, _own_application(request, pk))


@login_required
@require_http_methods(["GET", "POST"])
def application_edit(request, pk):
    application = _own_application(request, pk)
    if request.method == "POST":
        form = ApplicationForm(request.POST, request.FILES, instance=application, user=request.user)
        if form.is_valid():
            with transaction.atomic():
                form.save()
            messages.success(request, "Az alkalmazás módosításait elmentettük.")
            return redirect("application-detail", pk=application.pk)
    else:
        form = ApplicationForm(instance=application, user=request.user)

    return render(
        request,
        "dashboard/application_form.html",
        {"section": "applications", "form": form, "editing": True, "application": application},
    )


@login_required
@require_POST
def application_rotate_secret(request, pk):
    application = _own_application(request, pk)
    if application.client_type != Application.CLIENT_CONFIDENTIAL:
        messages.error(request, "Nyilvános alkalmazásnak nincs kliensjelszava.")
        return redirect("application-detail", pk=application.pk)

    new_secret = generate_client_secret()
    application.client_secret = new_secret
    application.save()
    messages.success(
        request,
        "Új kliensjelszót generáltunk. A régi azonnal érvénytelen.",
    )
    return _render_application(request, application, new_secret=new_secret)


@login_required
@require_POST
def application_delete(request, pk):
    application = _own_application(request, pk)
    name = application.name
    with transaction.atomic():
        if hasattr(application, "profile") and application.profile.logo:
            application.profile.logo.delete(save=False)
        application.delete()
    messages.success(request, f"A(z) „{name}” alkalmazást töröltük.")
    return redirect("applications")


def _active_grants(user):
    """Durable consents, including expired tokens and legacy token-only grants."""
    now = timezone.now()
    grants = []
    connections = {
        connection.application_id: connection
        for connection in UserAppConnection.objects.filter(user=user).select_related(
            "application", "application__profile"
        )
    }
    token_filter = Q(user=user)
    application_ids = set(connections) | set(
        AccessToken.objects.filter(token_filter, expires__gt=now).values_list(
            "application_id", flat=True
        )
    ) | set(
        RefreshToken.objects.filter(token_filter, revoked__isnull=True).values_list(
            "application_id", flat=True
        )
    )
    for application in Application.objects.filter(pk__in=application_ids).select_related("profile"):
        tokens = AccessToken.objects.filter(user=user, application=application).order_by("-created")
        latest = tokens.first()
        connection = connections.get(application.pk)
        first = tokens.last()
        grants.append(
            {
                "application": application,
                "scopes": describe_scopes(
                    connection.scopes if connection else (latest.scope.split() if latest else [])
                ),
                "authorized_at": (
                    connection.created_at if connection else (first.created if first else None)
                ),
                "last_used": (
                    connection.last_used_at if connection else None
                ) or (latest.created if latest else None),
                "interaction_mode": (
                    connection.interaction_mode
                    if connection
                    else UserAppConnection.InteractionMode.CONFIRM
                ),
                "has_connection": connection is not None,
            }
        )
    return sorted(grants, key=lambda grant: grant["last_used"] or now, reverse=True)


@login_required
def grants(request):
    return render(
        request,
        "dashboard/grants.html",
        {"section": "grants", "grants": _active_grants(request.user)},
    )


@login_required
@require_POST
def grant_revoke(request, pk):
    application = get_object_or_404(Application, pk=pk)
    user = request.user
    with transaction.atomic():
        for model in (RefreshToken, AccessToken, IDToken, Grant):
            model.objects.filter(user=user, application=application).delete()
        UserAppConnection.objects.filter(user=user, application=application).delete()
    messages.success(request, f"A(z) „{application.name}” hozzáférését visszavontuk.")
    return redirect("grants")


@login_required
@require_POST
def grant_interaction_update(request, pk):
    connection = get_object_or_404(
        UserAppConnection.objects.select_related("application"),
        user=request.user,
        application_id=pk,
    )
    mode = request.POST.get("interaction_mode")
    if mode not in UserAppConnection.InteractionMode.values:
        messages.error(request, "Érvénytelen belépési mód.")
    else:
        connection.interaction_mode = mode
        connection.save(update_fields=["interaction_mode"])
        messages.success(
            request,
            f"A(z) „{connection.application.name}” belépési beállítását frissítettük.",
        )
    return redirect("grants")
