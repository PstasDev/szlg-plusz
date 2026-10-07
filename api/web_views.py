import json
import logging
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django_ratelimit.decorators import ratelimit
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .models import GlobalConfig, Passkey
from .webauthn_services import (
    create_authentication_options,
    create_registration_options,
    verify_authentication,
    verify_registration,
)

logger = logging.getLogger(__name__)

PASSKEY_PROMO_SESSION_KEY = "passkey_promo_next"

# Signed cookie listing the users that have a passkey on this browser/device.
DEVICE_COOKIE = "szlg_jelkulcs"
DEVICE_COOKIE_SALT = "szlg.jelkulcs.device"
DEVICE_COOKIE_MAX_AGE = 400 * 24 * 60 * 60


def _device_users(request) -> set[str]:
    raw = request.get_signed_cookie(DEVICE_COOKIE, default="", salt=DEVICE_COOKIE_SALT)
    return {entry for entry in raw.split(",") if entry}


def _remember_device(request, response, user):
    users = _device_users(request) | {str(user.pk)}
    response.set_signed_cookie(
        DEVICE_COOKIE,
        ",".join(sorted(users)),
        salt=DEVICE_COOKIE_SALT,
        max_age=DEVICE_COOKIE_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=request.is_secure(),
    )
    return response


def _promo_kind(request, user) -> str | None:
    """Which passkey offer fits this password login, if any.

    "first": the user has no passkey at all. "device": the user has passkeys,
    but this browser/device has not been marked as one that holds one.
    """
    if not GlobalConfig.get_solo().promote_passkey:
        return None
    if not Passkey.objects.filter(user=user).exists():
        return "first"
    if str(user.pk) not in _device_users(request):
        return "device"
    return None


def _safe_next_url(request, value: str | None) -> str:
    if isinstance(value, str) and value and url_has_allowed_host_and_scheme(
        value,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return value
    return reverse("dashboard")


def _json_payload(request) -> dict:
    if len(request.body) > 1_000_000:
        raise ValueError("A kérés túl nagy.")
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("Érvénytelen kérés.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Érvénytelen kérés.")
    return payload


@require_GET
def login_page(request):
    next_url = _safe_next_url(request, request.GET.get("next"))
    if request.user.is_authenticated:
        return redirect(next_url)
    return render(request, "auth/login.html", {"next_url": next_url})


@require_POST
@ratelimit(key="ip", rate="30/m", method="POST", block=True)
@ratelimit(key="post:email", rate="10/m", method="POST", block=True)
def password_login(request):
    email = request.POST.get("email", "").strip().lower()
    user = authenticate(request, email=email, password=request.POST.get("password", ""))
    next_url = _safe_next_url(request, request.POST.get("next"))
    if user is None or not user.is_active:
        return render(
            request,
            "auth/login.html",
            {
                "next_url": next_url,
                "email": email,
                "error": "A megadott e-mail-cím vagy jelszó nem megfelelő.",
            },
            status=401,
        )
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    # Only password logins get here; passkey logins never need the offer.
    if _promo_kind(request, user):
        request.session[PASSKEY_PROMO_SESSION_KEY] = next_url
        return redirect("passkey-promo")
    return redirect(next_url)


@require_POST
@ratelimit(key="ip", rate="30/m", method="POST", block=True)
def passkey_login_options(request):
    try:
        payload = _json_payload(request)
        email = payload.get("email", "")
        if not isinstance(email, str):
            raise ValueError("Érvénytelen e-mail-cím.")
        options, challenge_id = create_authentication_options(email)
        return JsonResponse({"options": options, "challenge_id": challenge_id})
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@require_POST
@ratelimit(key="ip", rate="15/m", method="POST", block=True)
def passkey_login_verify(request):
    try:
        payload = _json_payload(request)
        challenge_id = payload.get("challenge_id")
        credential = payload.get("credential")
        if (
            not isinstance(challenge_id, str)
            or not isinstance(credential, dict)
        ):
            raise ValueError("Érvénytelen jelkulcs-válasz.")
        user = verify_authentication(challenge_id, credential)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    response = JsonResponse({"redirect": _safe_next_url(request, payload.get("next"))})
    # A passkey just worked here, so this device needs no offer.
    return _remember_device(request, response, user)


@login_required
@require_POST
@ratelimit(key="user", rate="10/m", method="POST", block=True)
def passkey_registration_options(request):
    return JsonResponse(create_registration_options(request.user))


@login_required
@require_POST
@ratelimit(key="user", rate="10/m", method="POST", block=True)
def passkey_registration_verify(request):
    try:
        payload = _json_payload(request)
        credential = payload.get("credential")
        name = payload.get("name", "Jelkulcs")
        if not isinstance(credential, dict) or not isinstance(name, str):
            raise ValueError("Érvénytelen jelkulcs-válasz.")
        verify_registration(request.user, credential, name)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    redirect_to = reverse("security")
    if payload.get("promo") is True:
        promo_next = request.session.pop(PASSKEY_PROMO_SESSION_KEY, None)
        if promo_next:
            redirect_to = _safe_next_url(request, promo_next)
    response = JsonResponse({"redirect": redirect_to})
    return _remember_device(request, response, request.user)


@login_required
@require_http_methods(["GET", "POST"])
def passkey_promo(request):
    """Offered after a password login; "later" simply continues."""
    next_url = request.session.get(PASSKEY_PROMO_SESSION_KEY)
    kind = _promo_kind(request, request.user)
    if not next_url or not kind:
        request.session.pop(PASSKEY_PROMO_SESSION_KEY, None)
        return redirect(_safe_next_url(request, next_url))
    if request.method == "POST":
        request.session.pop(PASSKEY_PROMO_SESSION_KEY, None)
        response = redirect(_safe_next_url(request, next_url))
        if request.POST.get("device_ready") == "1":
            # "This device already has one": stop asking on this browser.
            _remember_device(request, response, request.user)
        return response
    return render(
        request,
        "auth/passkey_promo.html",
        {"next_url": next_url, "has_passkeys": kind == "device"},
    )


@login_required
@require_POST
def passkey_delete(request, passkey_id: int):
    deleted, _ = Passkey.objects.filter(id=passkey_id, user=request.user).delete()
    if not deleted:
        return JsonResponse({"error": "A jelkulcs nem található."}, status=404)
    return redirect("security")


@require_POST
def logout_view(request):
    logout(request)
    return redirect("login")


def csrf_failure(request, reason=""):
    """A readable 403 for failed CSRF checks, with the technical reason for admins."""
    logger.warning("CSRF check failed on %s: %s", request.path, reason)
    return render(request, "csrf_failure.html", {"reason": reason}, status=403)
