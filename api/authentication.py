import jwt
from django.contrib.auth.models import User
from django.http import HttpRequest
from ninja.security import HttpBearer

from .jwt_utils import decode_jwt_token


class JWTAuth(HttpBearer):
    def authenticate(self, request: HttpRequest, token: str) -> User | None:
        try:
            payload = decode_jwt_token(token)
        except (jwt.InvalidTokenError, TypeError, ValueError):
            return None

        if not isinstance(payload, dict):
            return None
        user_id = payload.get("user_id")
        if not isinstance(user_id, int) or user_id <= 0:
            return None
        try:
            return User.objects.get(pk=user_id, is_active=True)
        except User.DoesNotExist:
            return None
