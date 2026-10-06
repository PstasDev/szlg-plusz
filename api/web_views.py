import json
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django_ratelimit.decorators import ratelimit
from django.views.decorators.http import require_GET, require_POST

from .models import Passkey
from .webauthn_services import (
    create_authentication_options,
    create_registration_options,
    verify_authentication,
    verify_registration,
)

def _safe_next_url(request, value: str | None) -> str:
    if isinstance(value, str) and value and url_has_allowed_host_and_scheme(
        value,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return value
    return reverse("account")


def _json_payload(request) -> dict:
    if len(request.body) > 1_000_000:
        raise ValueError("Request body is too large.")
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid JSON request.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Invalid JSON request.")
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
    return redirect(next_url)


@require_POST
@ratelimit(key="ip", rate="30/m", method="POST", block=True)
def passkey_login_options(request):
    try:
        payload = _json_payload(request)
        email = payload.get("email", "")
        if not isinstance(email, str):
            raise ValueError("Invalid email address.")
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
            raise ValueError("Invalid passkey response.")
        user = verify_authentication(challenge_id, credential)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return JsonResponse({"redirect": _safe_next_url(request, payload.get("next"))})


@login_required
@require_GET
def account_page(request):
    return render(
        request,
        "auth/account.html",
        {"passkeys": Passkey.objects.filter(user=request.user)},
    )


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
        name = payload.get("name", "Passkey")
        if not isinstance(credential, dict) or not isinstance(name, str):
            raise ValueError("Invalid passkey response.")
        verify_registration(request.user, credential, name)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"redirect": reverse("account")})


@login_required
@require_POST
def passkey_delete(request, passkey_id: int):
    deleted, _ = Passkey.objects.filter(id=passkey_id, user=request.user).delete()
    if not deleted:
        return JsonResponse({"error": "Passkey not found."}, status=404)
    return redirect("account")


@require_POST
def logout_view(request):
    logout(request)
    return redirect("login")
