from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from django.conf import settings
from django.contrib.auth.models import User


def generate_jwt_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    expiration = now + timedelta(seconds=settings.JWT_EXPIRATION_DELTA)
    payload = {
        "user_id": user.id,
        "username": user.username,
        "iat": int(now.timestamp()),
        "exp": int(expiration.timestamp()),
    }
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_jwt_token(token: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
