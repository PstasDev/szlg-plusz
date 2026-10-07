from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.db import transaction
from django.db.models import Q
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

from .forms import ApplicationForm
from .models import Passkey
from .scopes import describe_scopes

MAX_APPLICATIONS_PER_USER = 10


def _own_application(request, pk):
    return get_object_or_404(
        Application.objects.select_related("profile"), pk=pk, user=request.user
    )


@login_required
@require_GET
def dashboard(request):
    user = request.user
    return render(
        request,
        "dashboard/profile.html",
        {
            "section": "profile",
            "student_profile": getattr(user, "student_profile", None),
            "teacher_profile": getattr(user, "teacher_profile", None),
            "school_groups": user.manual_groups.all(),
            "permission_groups": user.groups.all(),
            "has_password": user.has_usable_password(),
            "passkey_count": Passkey.objects.filter(user=user).count(),
            "grant_count": len(_active_grants(user)),
            "application_count": Application.objects.filter(user=user).count(),
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
    return render(
        request,
        "dashboard/application_detail.html",
        {
            "section": "applications",
            "application": application,
            "redirect_uris": application.redirect_uris.split(),
            "new_secret": new_secret,
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
    """Applications the user has authorized and that still hold usable tokens."""
    now = timezone.now()
    token_filter = Q(user=user)
    application_ids = set(
        AccessToken.objects.filter(token_filter, expires__gt=now).values_list("application_id", flat=True)
    ) | set(
        RefreshToken.objects.filter(token_filter, revoked__isnull=True).values_list(
            "application_id", flat=True
        )
    )
    grants = []
    for application in Application.objects.filter(pk__in=application_ids).select_related("profile"):
        tokens = AccessToken.objects.filter(user=user, application=application).order_by("-created")
        latest = tokens.first()
        first = tokens.last()
        grants.append(
            {
                "application": application,
                "scopes": describe_scopes(latest.scope.split()) if latest else [],
                "authorized_at": first.created if first else None,
                "last_used": latest.created if latest else None,
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
    messages.success(request, f"A(z) „{application.name}” hozzáférését visszavontuk.")
    return redirect("grants")
