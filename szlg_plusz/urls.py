from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.views.generic.base import RedirectView
from django.urls import include, path, re_path
from . import views

from api.web_views import (
    account_page,
    login_page,
    logout_view,
    passkey_delete,
    passkey_login_options,
    passkey_login_verify,
    passkey_registration_options,
    passkey_registration_verify,
    password_login,
)

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="login", permanent=False)),
    path("admin/", admin.site.urls),
    path("login/", login_page, name="login"),
    path("login/password/", password_login, name="password-login"),
    path("login/passkey/options/", passkey_login_options, name="passkey-login-options"),
    path("login/passkey/verify/", passkey_login_verify, name="passkey-login-verify"),
    path("account/", account_page, name="account"),
    path(
        "account/passkeys/register/options/",
        passkey_registration_options,
        name="passkey-registration-options",
    ),
    path(
        "account/passkeys/register/verify/",
        passkey_registration_verify,
        name="passkey-registration-verify",
    ),
    path(
        "account/passkeys/<int:passkey_id>/delete/",
        passkey_delete,
        name="passkey-delete",
    ),
    path("logout/", logout_view, name="logout"),
    path("o/", include("oauth2_provider.urls", namespace="oauth2_provider")),
]

urlpatterns += [
    re_path(r"^static/(?P<path>.*)$", views.serve_static, name="static"),
    re_path(r"^media/(?P<path>.*)$", views.serve_media, name="media"),
]
