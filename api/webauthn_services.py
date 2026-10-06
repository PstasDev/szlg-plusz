import base64
import json
import logging
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils import timezone
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from .auth_challenges import consume_challenge, store_challenge
from .models import Passkey

logger = logging.getLogger(__name__)
User = get_user_model()


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _expected_origins() -> list[str]:
    return list(settings.WEBAUTHN_ORIGINS)


def _rp_id() -> str:
    return settings.WEBAUTHN_RP_ID


def _registration_key(user_id: int) -> str:
    return f"passkey:registration:{user_id}"


def create_registration_options(user) -> dict:
    credentials = [
        PublicKeyCredentialDescriptor(id=bytes(item.credential_id))
        for item in Passkey.objects.filter(user=user)
    ]
    options = generate_registration_options(
        rp_id=_rp_id(),
        rp_name=settings.WEBAUTHN_RP_NAME,
        user_id=str(user.pk).encode("ascii"),
        user_name=user.email,
        user_display_name=user.get_full_name() or user.email,
        exclude_credentials=credentials,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        supported_pub_key_algs=[
            COSEAlgorithmIdentifier.ECDSA_SHA_256,
            COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256,
        ],
    )
    store_challenge(
        _registration_key(user.pk),
        _b64url_encode(options.challenge),
        user_id=user.pk,
    )
    return json.loads(options_to_json(options))


def verify_registration(user, credential: dict, name: str = "Passkey") -> Passkey:
    challenge = consume_challenge(_registration_key(user.pk))
    if challenge is None or challenge["user_id"] != user.pk:
        raise ValueError("Passkey registration has expired. Start again.")
    try:
        verification = verify_registration_response(
            credential=credential,
            expected_challenge=_b64url_decode(challenge["challenge"]),
            expected_rp_id=_rp_id(),
            expected_origin=_expected_origins(),
            require_user_verification=True,
        )
    except Exception as exc:
        logger.warning("Passkey registration verification failed for user %s", user.pk)
        raise ValueError("Passkey registration failed.") from exc
    response = credential.get("response")
    transports = response.get("transports", []) if isinstance(response, dict) else []
    if not isinstance(transports, list):
        transports = []
    try:
        return Passkey.objects.create(
            user=user,
            credential_id=verification.credential_id,
            public_key=verification.credential_public_key,
            sign_count=verification.sign_count,
            transports=",".join(
                value for value in transports if isinstance(value, str)
            )[:200],
            name=(name.strip() or "Passkey")[:80],
        )
    except IntegrityError as exc:
        logger.warning("Duplicate passkey registration for user %s", user.pk)
        raise ValueError("This passkey is already registered.") from exc


def create_authentication_options(email: str = "") -> tuple[dict, str]:
    user = None
    if email:
        try:
            user = User.objects.get(email=email.strip().lower(), is_active=True)
        except User.DoesNotExist:
            user = None

    options = generate_authentication_options(
        rp_id=_rp_id(),
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    challenge_id = secrets.token_urlsafe(24)
    store_challenge(
        f"passkey:authentication:{challenge_id}",
        _b64url_encode(options.challenge),
        user_id=user.pk if user is not None else None,
        account_hint_provided=bool(email),
    )
    return json.loads(options_to_json(options)), challenge_id


def verify_authentication(challenge_id: str, credential: dict):
    challenge = consume_challenge(f"passkey:authentication:{challenge_id}")
    if challenge is None:
        raise ValueError("Passkey login has expired. Start again.")

    raw_id = credential.get("rawId")
    if not isinstance(raw_id, str):
        raise ValueError("Invalid passkey credential.")
    try:
        credential_id = _b64url_decode(raw_id)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid passkey credential.") from exc

    passkey = (
        Passkey.objects.select_related("user")
        .filter(credential_id=credential_id)
        .first()
    )
    if passkey is None or not passkey.user.is_active:
        raise ValueError("Passkey authentication failed.")
    if challenge["account_hint_provided"] and (
        challenge["user_id"] is None or challenge["user_id"] != passkey.user_id
    ):
        raise ValueError("Passkey authentication failed.")

    try:
        verification = verify_authentication_response(
            credential=credential,
            expected_challenge=_b64url_decode(challenge["challenge"]),
            expected_rp_id=_rp_id(),
            expected_origin=_expected_origins(),
            credential_public_key=bytes(passkey.public_key),
            credential_current_sign_count=passkey.sign_count,
            require_user_verification=True,
        )
    except Exception as exc:
        logger.warning("Passkey authentication verification failed for credential %s", passkey.pk)
        raise ValueError("Passkey authentication failed.") from exc

    passkey.sign_count = verification.new_sign_count
    passkey.last_used_at = timezone.now()
    passkey.save(update_fields=["sign_count", "last_used_at"])
    return passkey.user
