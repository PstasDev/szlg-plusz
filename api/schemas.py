from ninja import Schema


class LoginRequest(Schema):
    username: str
    password: str


class TokenResponse(Schema):
    token: str
    user_id: int
    username: str
    iat: int
    exp: int


class ErrorResponse(Schema):
    error: str
    detail: str


class UserResponse(Schema):
    id: int
    username: str
    first_name: str
    last_name: str
    email: str
