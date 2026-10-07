import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

from api.scopes import SCOPE_SHORT_DESCRIPTIONS

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise ImproperlyConfigured("SECRET_KEY must be set in the environment.")

DEBUG = env_bool("DEBUG", False)
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "mptt",
    "solo",
    "oauth2_provider",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "szlg_plusz.urls"
WSGI_APPLICATION = "szlg_plusz.wsgi.application"
ASGI_APPLICATION = "szlg_plusz.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {"timeout": 20},
    }
}

AUTH_USER_MODEL = "api.CustomUser"
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "hu-hu"
TIME_ZONE = "Europe/Budapest"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"
PASSWORD_RESET_TIMEOUT = 60 * 60
CSRF_FAILURE_VIEW = "api.web_views.csrf_failure"

EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend"
    if DEBUG
    else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "SZLG+ <noreply@sso.szlg.info>")

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", not DEBUG)
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", not DEBUG)
SECURE_HSTS_SECONDS = int(
    os.environ.get("SECURE_HSTS_SECONDS", "0" if DEBUG else "31536000")
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)
if env_bool("USE_X_FORWARDED_PROTO", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

CORS_ALLOW_ALL_ORIGINS = env_bool("CORS_ALLOW_ALL_ORIGINS", False)
CORS_ALLOW_CREDENTIALS = False
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

WEBAUTHN_RP_ID = os.environ.get("WEBAUTHN_RP_ID", "localhost")
WEBAUTHN_RP_NAME = os.environ.get("WEBAUTHN_RP_NAME", "SZLG+")
WEBAUTHN_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "WEBAUTHN_ORIGINS", "http://localhost:8002,http://127.0.0.1:8002"
    ).split(",")
    if origin.strip()
]

private_key_path = Path(
    os.environ.get(
        "OIDC_RSA_PRIVATE_KEY_FILE",
        str(BASE_DIR / ".secrets" / "oidc-private.pem"),
    )
)
if not private_key_path.is_absolute():
    private_key_path = BASE_DIR / private_key_path
try:
    OIDC_RSA_PRIVATE_KEY = private_key_path.read_text(encoding="ascii")
except FileNotFoundError as exc:
    raise ImproperlyConfigured(
        f"OIDC signing key not found at {private_key_path}. Generate it with "
        "`python scripts/generate_oidc_key.py` or point OIDC_RSA_PRIVATE_KEY_FILE "
        "to an existing key."
    ) from exc

OAUTH2_PROVIDER_APPLICATION_MODEL = "oauth2_provider.Application"

OAUTH2_PROVIDER = {
    "OIDC_ENABLED": True,
    "OIDC_RSA_PRIVATE_KEY": OIDC_RSA_PRIVATE_KEY,
    "OAUTH2_VALIDATOR_CLASS": "api.oauth.SZLGPlusOAuth2Validator",
    "SCOPES": SCOPE_SHORT_DESCRIPTIONS,
    "DEFAULT_SCOPES": ["openid"],
    "ACCESS_TOKEN_EXPIRE_SECONDS": 3600,
    "ID_TOKEN_EXPIRE_SECONDS": 3600,
    "PKCE_REQUIRED": True,
    "COMPLIANT_BCP_RFC9700_PKCE_METHOD": True,
    "OIDC_RESPONSE_TYPES_SUPPORTED": ["code"],
    "ALLOWED_REDIRECT_URI_SCHEMES": ["https"] + (["http"] if DEBUG else []),
    "ALLOW_URI_WILDCARDS": False,
    "ALLOW_LOCALHOST_LOOPBACK": env_bool("ALLOW_LOCALHOST_LOOPBACK", False),
    "COMPLIANT_BCP_RFC9700_IMPLICIT_GRANT": True,
    "COMPLIANT_BCP_RFC9700_PASSWORD_GRANT": True,
    "COMPLIANT_BCP_RFC9700_PKCE_REQUIRED": True,
    "COMPLIANT_BCP_RFC9700_ACCESS_TOKEN_TRANSPORT": True,
    "COMPLIANT_BCP_RFC9700_AUTHZ_RESPONSE_ISS": True,
    "COMPLIANT_BCP_RFC9700_TOKEN_STORAGE": True,
    "REFRESH_TOKEN_REUSE_PROTECTION": True,
    "COMPLIANT_BCP_RFC9700_REFRESH_TOKEN": True,
    "COMPLIANT_BCP_RFC9700_REDIRECT_URI_SCHEME": not DEBUG,
    "COMPLIANT_BCP_RFC9700_REDIRECT_URI_MATCHING": True,
    "DCR_ENABLED": False,
    "CIMD_ENABLED": False,
}
