"""
WebAuthn / Passkey authentication endpoints.

Exposes:
    POST /passkey/register/options   (auth=jwt) - begin enrollment
    POST /passkey/register/verify    (auth=jwt) - finish enrollment
    POST /passkey/authenticate/options (auth=None) - begin login
    POST /passkey/authenticate/verify  (auth=None) - finish login (returns JWT)
    GET  /passkey                    (auth=jwt) - list user's passkeys
    DELETE /passkey/{passkey_id}     (auth=jwt) - remove a passkey
    POST /change-password            (auth=jwt) - change current user's password
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Optional

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.utils import timezone
from ninja import Schema, Body
from pydantic import ConfigDict

from webauthn import (
    generate_registration_options,
    generate_authentication_options,
    verify_registration_response,
    verify_authentication_response,
    options_to_json,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
    PublicKeyCredentialDescriptor,
)
from webauthn.helpers.cose import COSEAlgorithmIdentifier

from .models import Passkey, Profile
from .schemas import ErrorResponse, TokenResponse
from .jwt_utils import generate_jwt_token, decode_jwt_token

logger = logging.getLogger(__name__)

# Challenge TTL: 5 minutes.
CHALLENGE_TTL = 300


# ---------- helpers ----------

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _rp_id() -> str:
    return getattr(settings, "WEBAUTHN_RP_ID", "localhost")


def _rp_name() -> str:
    return getattr(settings, "WEBAUTHN_RP_NAME", "Igazoláskezelő")


def _expected_origins() -> list[str]:
    origins = getattr(settings, "WEBAUTHN_ORIGINS", None)
    if origins:
        if isinstance(origins, str):
            return [o.strip() for o in origins.split(",") if o.strip()]
        return list(origins)
    # Sensible defaults for development.
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://igazolas.szlg.info",
    ]


def _reg_cache_key(user_id: int) -> str:
    return f"passkey:reg:{user_id}"


def _auth_cache_key(challenge_id: str) -> str:
    return f"passkey:auth:{challenge_id}"


# ---------- ninja schemas ----------

class PasskeyInfo(Schema):
    id: int
    name: str
    created_at: str
    last_used_at: Optional[str] = None


class PasskeyListResponse(Schema):
    has_passkey: bool
    passkeys: list[PasskeyInfo]


class PasskeyRegisterOptionsRequest(Schema):
    name: Optional[str] = None


class PasskeyRegisterVerifyRequest(Schema):
    model_config = ConfigDict(extra="allow")
    name: Optional[str] = None
    response: dict  # full PublicKeyCredential JSON from navigator.credentials.create()


class PasskeyAuthOptionsRequest(Schema):
    username: Optional[str] = None


class PasskeyAuthOptionsResponse(Schema):
    options: dict
    challenge_id: str


class PasskeyAuthVerifyRequest(Schema):
    challenge_id: str
    response: dict


class ChangePasswordRequest(Schema):
    old_password: str
    new_password: str


class SimpleMessageResponse(Schema):
    message: str


# ---------- endpoint registration ----------

def register_passkey_endpoints(api, jwt_auth):
    """Attach passkey + change-password endpoints to the provided NinjaAPI."""

    @api.get(
        "/passkey",
        response={200: PasskeyListResponse, 401: ErrorResponse},
        auth=jwt_auth,
        tags=["Passkey"],
    )
    def list_passkeys(request):
        user = request.auth
        items = Passkey.objects.filter(user=user).order_by("-created_at")
        data = [
            PasskeyInfo(
                id=p.id,
                name=p.name or "Passkey",
                created_at=p.created_at.isoformat() if p.created_at else "",
                last_used_at=p.last_used_at.isoformat() if p.last_used_at else None,
            )
            for p in items
        ]
        return 200, {"has_passkey": bool(data), "passkeys": data}

    @api.delete(
        "/passkey/{passkey_id}",
        response={200: SimpleMessageResponse, 401: ErrorResponse, 404: ErrorResponse},
        auth=jwt_auth,
        tags=["Passkey"],
    )
    def delete_passkey(request, passkey_id: int):
        user = request.auth
        try:
            p = Passkey.objects.get(id=passkey_id, user=user)
        except Passkey.DoesNotExist:
            return 404, {"error": "Not found", "detail": "Passkey not found"}
        p.delete()
        return 200, {"message": "Passkey törölve."}

    @api.post(
        "/passkey/register/options",
        response={200: dict, 401: ErrorResponse},
        auth=jwt_auth,
        tags=["Passkey"],
    )
    def passkey_register_options(request, data: PasskeyRegisterOptionsRequest = Body(None)):
        user = request.auth
        existing = Passkey.objects.filter(user=user)
        exclude = [
            PublicKeyCredentialDescriptor(id=bytes(p.credential_id))
            for p in existing
        ]

        opts = generate_registration_options(
            rp_id=_rp_id(),
            rp_name=_rp_name(),
            user_id=str(user.id).encode("utf-8"),
            user_name=user.username,
            user_display_name=user.get_full_name() or user.username,
            exclude_credentials=exclude,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.PREFERRED,
            ),
            supported_pub_key_algs=[
                COSEAlgorithmIdentifier.ECDSA_SHA_256,
                COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256,
            ],
        )

        cache.set(
            _reg_cache_key(user.id),
            {"challenge": _b64url_encode(opts.challenge)},
            CHALLENGE_TTL,
        )

        return 200, json.loads(options_to_json(opts))

    @api.post(
        "/passkey/register/verify",
        response={200: SimpleMessageResponse, 400: ErrorResponse, 401: ErrorResponse},
        auth=jwt_auth,
        tags=["Passkey"],
    )
    def passkey_register_verify(request, data: PasskeyRegisterVerifyRequest):
        user = request.auth
        cached = cache.get(_reg_cache_key(user.id))
        if not cached:
            return 400, {
                "error": "Bad request",
                "detail": "A regisztrációs kérés lejárt, próbáld újra.",
            }
        try:
            verification = verify_registration_response(
                credential=data.response,
                expected_challenge=_b64url_decode(cached["challenge"]),
                expected_rp_id=_rp_id(),
                expected_origin=_expected_origins(),
                require_user_verification=False,
            )
        except Exception as exc:  # noqa: BLE001 - WebAuthn lib raises various
            logger.warning("Passkey registration verify failed: %s", exc)
            return 400, {"error": "Verification failed", "detail": str(exc)}
        finally:
            cache.delete(_reg_cache_key(user.id))

        transports = []
        try:
            raw_response = data.response.get("response", {}) if isinstance(data.response, dict) else {}
            transports = raw_response.get("transports") or []
        except Exception:  # noqa: BLE001
            transports = []

        Passkey.objects.create(
            user=user,
            credential_id=verification.credential_id,
            public_key=verification.credential_public_key,
            sign_count=verification.sign_count,
            transports=",".join(t for t in transports if isinstance(t, str))[:200],
            name=(data.name or "Passkey")[:80],
        )
        return 200, {"message": "Passkey sikeresen rögzítve."}

    @api.post(
        "/passkey/authenticate/options",
        response={200: PasskeyAuthOptionsResponse, 400: ErrorResponse},
        auth=None,
        tags=["Passkey"],
    )
    def passkey_auth_options(request, data: PasskeyAuthOptionsRequest = Body(None)):
        allow = []
        user_id: Optional[int] = None
        if data and data.username:
            try:
                user = User.objects.get(username=data.username, is_active=True)
            except User.DoesNotExist:
                user = None
            if user is not None:
                user_id = user.id
                allow = [
                    PublicKeyCredentialDescriptor(id=bytes(p.credential_id))
                    for p in Passkey.objects.filter(user=user)
                ]
        opts = generate_authentication_options(
            rp_id=_rp_id(),
            allow_credentials=allow or None,
            user_verification=UserVerificationRequirement.PREFERRED,
        )
        challenge_id = _b64url_encode(opts.challenge)[:32]
        cache.set(
            _auth_cache_key(challenge_id),
            {
                "challenge": _b64url_encode(opts.challenge),
                "user_id": user_id,
            },
            CHALLENGE_TTL,
        )
        return 200, {
            "options": json.loads(options_to_json(opts)),
            "challenge_id": challenge_id,
        }

    @api.post(
        "/passkey/authenticate/verify",
        response={200: TokenResponse, 400: ErrorResponse, 401: ErrorResponse},
        auth=None,
        tags=["Passkey"],
    )
    def passkey_auth_verify(request, data: PasskeyAuthVerifyRequest):
        cached = cache.get(_auth_cache_key(data.challenge_id))
        if not cached:
            return 400, {
                "error": "Bad request",
                "detail": "A bejelentkezési kérés lejárt, próbáld újra.",
            }
        cache.delete(_auth_cache_key(data.challenge_id))

        raw_id_b64 = data.response.get("rawId") if isinstance(data.response, dict) else None
        if not raw_id_b64:
            return 400, {"error": "Bad request", "detail": "Hibás passkey válasz."}
        try:
            raw_id_bytes = _b64url_decode(raw_id_b64)
        except Exception:
            return 400, {"error": "Bad request", "detail": "Hibás passkey azonosító."}

        passkey = Passkey.objects.filter(credential_id=raw_id_bytes).select_related("user").first()
        if not passkey:
            return 401, {"error": "Unauthorized", "detail": "Ismeretlen passkey."}
        if cached.get("user_id") and cached["user_id"] != passkey.user_id:
            return 401, {"error": "Unauthorized", "detail": "Passkey nem ehhez a fiókhoz tartozik."}

        try:
            verification = verify_authentication_response(
                credential=data.response,
                expected_challenge=_b64url_decode(cached["challenge"]),
                expected_rp_id=_rp_id(),
                expected_origin=_expected_origins(),
                credential_public_key=bytes(passkey.public_key),
                credential_current_sign_count=passkey.sign_count,
                require_user_verification=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Passkey auth verify failed: %s", exc)
            return 401, {"error": "Unauthorized", "detail": "Passkey ellenőrzés sikertelen."}

        passkey.sign_count = verification.new_sign_count
        passkey.last_used_at = timezone.now()
        passkey.save(update_fields=["sign_count", "last_used_at"])

        user = passkey.user
        if not user.is_active:
            return 401, {"error": "Unauthorized", "detail": "A fiók le van tiltva."}

        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.login_count = (profile.login_count or 0) + 1
        profile.save(update_fields=["login_count"])

        token = generate_jwt_token(user)
        payload = decode_jwt_token(token)
        return 200, {
            "token": token,
            "user_id": user.id,
            "username": user.username,
            "iat": payload["iat"],
            "exp": payload["exp"],
        }

    @api.post(
        "/change-password",
        response={200: SimpleMessageResponse, 400: ErrorResponse, 401: ErrorResponse},
        auth=jwt_auth,
        tags=["Account"],
    )
    def change_password(request, data: ChangePasswordRequest):
        user = request.auth
        if not user.check_password(data.old_password):
            return 401, {"error": "Unauthorized", "detail": "A jelenlegi jelszó hibás."}
        if len(data.new_password or "") < 8:
            return 400, {"error": "Bad request", "detail": "Az új jelszó legalább 8 karakter legyen."}
        user.set_password(data.new_password)
        user.save(update_fields=["password"])
        return 200, {"message": "Jelszó sikeresen módosítva."}
