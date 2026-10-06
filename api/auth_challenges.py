from datetime import timedelta
from typing import TypedDict

from django.db import transaction
from django.utils import timezone

from .models import WebAuthnChallenge


CHALLENGE_TTL_SECONDS = 300


class ChallengeData(TypedDict):
    challenge: str
    user_id: int | None


def store_challenge(key: str, challenge: str, user_id: int | None = None) -> None:
    now = timezone.now()
    WebAuthnChallenge.objects.filter(expires_at__lte=now).delete()
    WebAuthnChallenge.objects.update_or_create(
        key=key,
        defaults={
            "challenge": challenge,
            "user_id": user_id,
            "expires_at": now + timedelta(seconds=CHALLENGE_TTL_SECONDS),
        },
    )


def consume_challenge(key: str) -> ChallengeData | None:
    with transaction.atomic():
        record = WebAuthnChallenge.objects.select_for_update().filter(key=key).first()
        if record is None:
            return None

        if record.expires_at <= timezone.now():
            record.delete()
            return None

        result: ChallengeData = {
            "challenge": record.challenge,
            "user_id": record.user_id,
        }
        record.delete()
        return result
