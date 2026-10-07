from django.contrib import admin
from django.urls import include, path
from django.views.generic.base import RedirectView

from api import dashboard_views, password_reset_views
from api.web_views import (
    login_page,
    logout_view,
    passkey_delete,
    passkey_login_options,
    passkey_login_verify,
    passkey_promo,
    passkey_registration_options,
    passkey_registration_verify,
    password_login,
)

urlpatterns = [
    path("", dashboard_views.dashboard, name="dashboard"),
    path("admin/", admin.site.urls),
    path("login/", login_page, name="login"),
    path("login/password/", password_login, name="password-login"),
    path("login/passkey/options/", passkey_login_options, name="passkey-login-options"),
    path("login/passkey/verify/", passkey_login_verify, name="passkey-login-verify"),
    path("login/passkey/offer/", passkey_promo, name="passkey-promo"),
    path("logout/", logout_view, name="logout"),
    path("security/", dashboard_views.security, name="security"),
    path("apps/", dashboard_views.applications, name="applications"),
    path("apps/new/", dashboard_views.application_new, name="application-new"),
    path("apps/<int:pk>/", dashboard_views.application_detail, name="application-detail"),
    path("apps/<int:pk>/edit/", dashboard_views.application_edit, name="application-edit"),
    path(
        "apps/<int:pk>/rotate-secret/",
        dashboard_views.application_rotate_secret,
        name="application-rotate-secret",
    ),
    path("apps/<int:pk>/delete/", dashboard_views.application_delete, name="application-delete"),
    path("grants/", dashboard_views.grants, name="grants"),
    path("grants/<int:pk>/revoke/", dashboard_views.grant_revoke, name="grant-revoke"),
    path("password/reset/", password_reset_views.PasswordResetRequestView.as_view(), name="password-reset"),
    path("password/reset/sent/", password_reset_views.PasswordResetSentView.as_view(), name="password-reset-done"),
    path(
        "password/reset/<uidb64>/<token>/",
        password_reset_views.PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    path(
        "password/reset/complete/",
        password_reset_views.PasswordResetFinishedView.as_view(),
        name="password-reset-complete",
    ),
    path("account/", RedirectView.as_view(pattern_name="security", permanent=False), name="account"),
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
    path("o/", include("szlg_plusz.oidc_urls", namespace="oauth2_provider")),
    path("", include("statichandler.urls")),
]