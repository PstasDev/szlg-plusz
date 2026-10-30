from django.contrib import admin
from django.urls import include, path
from django.views.generic.base import RedirectView

from api import dashboard_views, password_reset_views
from api import portal_views
from api import registration_views
from api import school_account_views
from api import student_profile_views
from api import user_import_views
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
    path("", portal_views.landing, name="home"),
    path(
        "tamogatott-alkalmazasok/",
        portal_views.supported_applications,
        name="supported-applications",
    ),
    path("dashboard/", dashboard_views.dashboard, name="dashboard"),
    path("docs/", portal_views.docs, name="docs"),
    path("adatvedelem/", portal_views.privacy, name="privacy"),
    path("docs/felhasznalok/", portal_views.docs, {"slug": "felhasznalok"}, name="docs-users"),
    path("docs/adminisztratorok/", portal_views.docs, {"slug": "adminok"}, name="docs-admins"),
    path(
        "docs/alkalmazas-fejlesztok/",
        portal_views.docs,
        {"slug": "alkalmazas-fejlesztok"},
        name="docs-app-developers",
    ),
    path(
        "docs/szlg-fejlesztok/",
        portal_views.docs,
        {"slug": "szlg-fejlesztok"},
        name="docs-szlg-developers",
    ),
    # Preserve old deep links while organizing the documentation by audience.
    path("docs/csoportok/", portal_views.docs, {"slug": "adminok"}, name="docs-groups"),
    path(
        "docs/fejlesztok/oidc/",
        portal_views.docs,
        {"slug": "alkalmazas-fejlesztok"},
        name="docs-oidc",
    ),
    path("docs/passkey/", portal_views.docs, {"slug": "felhasznalok"}, name="docs-passkey"),
    path("admin/user-import/", user_import_views.user_import_page, name="user-import"),
    path(
        "admin/user-import/preview/",
        user_import_views.user_import_preview,
        name="user-import-preview",
    ),
    path(
        "admin/user-import/one/",
        user_import_views.user_import_one,
        name="user-import-one",
    ),
    path(
        "admin/manual-review/",
        school_account_views.manual_review_list,
        name="manual-review-list",
    ),
    path(
        "admin/manual-review/<int:pk>/",
        school_account_views.manual_review_detail,
        name="manual-review-detail",
    ),
    path("admin/", admin.site.urls),
    path("login/", login_page, name="login"),
    path("register/", registration_views.register, name="register"),
    path(
        "account/school/",
        school_account_views.school_account_setup,
        name="school-account-setup",
    ),
    path(
        "account/school/otp/",
        school_account_views.school_account_otp,
        name="school-account-otp",
    ),
    path(
        "account/school/password/",
        school_account_views.school_account_password,
        name="school-account-password",
    ),
    path(
        "account/school/register/",
        school_account_views.school_account_register,
        name="school-account-register",
    ),
    path(
        "account/school/submitted/",
        school_account_views.school_account_submitted,
        name="school-account-submitted",
    ),
    path(
        "email/confirm/resend/",
        registration_views.resend_confirmation,
        name="email-confirm-resend",
    ),
    path(
        "email/confirm/<str:token>/",
        registration_views.email_confirmation,
        name="email-confirm",
    ),
    path(
        "email/confirmed/",
        registration_views.email_confirmation_complete,
        name="email-confirmed",
    ),
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
    path(
        "grants/<int:pk>/interaction/",
        dashboard_views.grant_interaction_update,
        name="grant-interaction-update",
    ),
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
    path("account/", RedirectView.as_view(pattern_name="profile", permanent=False), name="account"),
    path("account/profile/", dashboard_views.dashboard, name="profile"),
    path(
        "account/student-profile/complete/",
        student_profile_views.student_profile_completion,
        name="student-profile-completion",
    ),
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
