from django.contrib.auth import authenticate
from django.utils import timezone
from ninja import NinjaAPI

from .authentication import JWTAuth
from .jwt_utils import decode_jwt_token, generate_jwt_token
from .passkey_views import register_passkey_endpoints
from .schemas import ErrorResponse, LoginRequest, TokenResponse, UserResponse

api = NinjaAPI(
    title="SZLG+",
    version="1.0.0",
    description="SZLG+ authentication API",
)
jwt_auth = JWTAuth()

register_passkey_endpoints(api, jwt_auth)


@api.post(
    "/auth/password/login",
    response={200: TokenResponse, 401: ErrorResponse},
    auth=None,
    tags=["Authentication"],
)
def password_login(request, data: LoginRequest):
    user = authenticate(request, username=data.username, password=data.password)
    if user is None or not user.is_active:
        return 401, {
            "error": "Unauthorized",
            "detail": "Invalid username or password",
        }

    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])

    token = generate_jwt_token(user)
    payload = decode_jwt_token(token)
    return 200, {
        "token": token,
        "user_id": user.id,
        "username": user.username,
        "iat": payload["iat"],
        "exp": payload["exp"],
    }


@api.get(
    "/auth/me",
    response={200: UserResponse, 401: ErrorResponse},
    auth=jwt_auth,
    tags=["Authentication"],
)
def current_user(request):
    user = request.auth
    return 200, {
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
    }
