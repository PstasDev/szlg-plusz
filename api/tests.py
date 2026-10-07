import base64
import hashlib
import json
import re
import shutil
import tempfile
import manage
from datetime import timedelta
from html.parser import HTMLParser
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlparse

from django.conf import settings
from django.contrib.auth.models import Group
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from oauth2_provider.models import AccessToken, Application, RefreshToken
from jwcrypto.jwt import JWT
from PIL import Image

from .auth_challenges import consume_challenge
from .models import (
    ApplicationProfile,
    CustomUser,
    GlobalConfig,
    ManualGroup,
    Passkey,
    StudentProfile,
)
from .oauth import SZLGPlusOAuth2Validator
from .scopes import describe_scopes


class RunserverDefaultTests(TestCase):
    def test_runserver_uses_port_8002_when_no_address_was_supplied(self):
        self.assertEqual(
            manage.add_default_runserver_address(["manage.py", "runserver"]),
            ["manage.py", "runserver", "127.0.0.1:8002"],
        )
        self.assertEqual(
            manage.add_default_runserver_address(
                ["manage.py", "runserver", "--noreload"]
            ),
            ["manage.py", "runserver", "--noreload", "127.0.0.1:8002"],
        )

    def test_runserver_respects_explicit_address_and_non_runserver_commands(self):
        args = ["manage.py", "runserver", "0.0.0.0:9000"]
        self.assertEqual(manage.add_default_runserver_address(args), args)
        args = ["manage.py", "migrate"]
        self.assertEqual(manage.add_default_runserver_address(args), args)


class HiddenInputParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}
        self.form_action = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "form":
            self.form_action = attributes.get("action")
            return
        if tag != "input":
            return
        if attributes.get("type") == "hidden":
            self.values[attributes["name"]] = attributes.get("value", "")


class IdentityModelTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="Student@Example.org",
            password="test-password-123",
            first_name="Test",
            last_name="Student",
        )

    def test_email_is_normalized_and_role_profiles_are_smart_groups(self):
        self.assertEqual(self.user.email, "student@example.org")
        self.assertFalse(self.user.is_student)
        StudentProfile.objects.create(user=self.user, om_id="12345")
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_student)
        self.assertEqual(
            self.user.smart_groups,
            {"student": True, "teacher": False, "staff": False},
        )

    def test_nested_manual_group_paths_appear_in_oidc_claims(self):
        parent = ManualGroup.objects.create(name="Stúdiósok", slug="studiosok")
        child = ManualGroup.objects.create(
            name="Betanulók",
            slug="betanulok",
            parent=parent,
        )
        self.user.manual_groups.add(child)
        StudentProfile.objects.create(user=self.user)

        request = SimpleNamespace(
            user=self.user,
            scopes=["openid", "email", "profile", "groups"],
        )
        claims = SZLGPlusOAuth2Validator().get_oidc_claims(None, None, request)

        self.assertEqual(claims["sub"], str(self.user.oidc_subject))
        self.assertEqual(claims["email"], "student@example.org")
        self.assertEqual(claims["smart_groups"]["student"], True)
        self.assertEqual(
            claims["manual_groups"],
            ["studiosok", "studiosok/betanulok"],
        )

    def test_group_claims_require_the_groups_scope(self):
        request = SimpleNamespace(user=self.user, scopes=["openid"])
        claims = SZLGPlusOAuth2Validator().get_oidc_claims(None, None, request)

        self.assertEqual(claims["sub"], str(self.user.oidc_subject))
        self.assertNotIn("smart_groups", claims)
        self.assertNotIn("manual_groups", claims)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class LoginAndOIDCTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="student@example.org",
            password="test-password-123",
            first_name="Test",
        )

    def test_password_login_uses_session_and_rejects_external_next_url(self):
        response = self.client.post(
            "/login/password/",
            {
                "email": "STUDENT@example.org",
                "password": "test-password-123",
                "next": "https://attacker.invalid/",
            },
        )

        self.assertRedirects(response, "/login/passkey/offer/", fetch_redirect_response=False)
        self.assertEqual(self.client.session["passkey_promo_next"], "/")
        self.assertIn("_auth_user_id", self.client.session)

    def test_invalid_password_does_not_create_session(self):
        response = self.client.post(
            "/login/password/",
            {"email": self.user.email, "password": "wrong-password"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_page_and_discovery_document_are_available(self):
        self.assertEqual(self.client.get("/login/").status_code, 200)
        metadata = self.client.get("/o/.well-known/openid-configuration")
        self.assertEqual(metadata.status_code, 200)
        self.assertIn("/o/authorize/", metadata.json()["authorization_endpoint"])
        self.assertIn("/o/token/", metadata.json()["token_endpoint"])

    def test_passkey_login_options_do_not_disclose_account_existence(self):
        responses = []
        for email in ("student@example.org", "missing@example.org"):
            responses.append(
                self.client.post(
                    "/login/passkey/options/",
                    data=json.dumps({"email": email}),
                    content_type="application/json",
                ).json()
            )

        self.assertEqual(
            responses[0]["options"]["allowCredentials"],
            responses[1]["options"]["allowCredentials"],
        )
        self.assertEqual(responses[0]["options"]["allowCredentials"], [])
        key = f"passkey:authentication:{responses[0]['challenge_id']}"
        self.assertIsNotNone(consume_challenge(key))
        self.assertIsNone(consume_challenge(key))

    def test_authenticated_user_can_start_discoverable_passkey_registration(self):
        self.client.force_login(self.user)
        response = self.client.post(
            "/account/passkeys/register/options/",
            data="{}",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["authenticatorSelection"]["residentKey"],
            "required",
        )
        self.assertEqual(
            response.json()["authenticatorSelection"]["userVerification"],
            "required",
        )

    def test_custom_user_can_be_administered(self):
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save(update_fields=["is_staff", "is_superuser"])
        self.client.force_login(self.user)

        response = self.client.get("/admin/api/customuser/add/")

        self.assertEqual(response.status_code, 200)

    def test_authorization_code_pkce_returns_signed_id_token_with_custom_claims(self):
        StudentProfile.objects.create(user=self.user)
        group = ManualGroup.objects.create(name="Stúdiósok", slug="studiosok")
        self.user.manual_groups.add(group)
        application = Application.objects.create(
            name="SZLG+ client test",
            user=self.user,
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://client.example/callback",
            algorithm=Application.RS256_ALGORITHM,
        )
        verifier = "test-verifier-which-is-long-enough-for-pkce-0123456789"
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode("ascii")
        authorization = {
            "response_type": "code",
            "client_id": application.client_id,
            "redirect_uri": "https://client.example/callback",
            "scope": "openid profile email groups",
            "state": "test-state",
            "nonce": "test-nonce",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        self.client.force_login(self.user)
        consent = self.client.get(f"/o/authorize/?{urlencode(authorization)}")
        self.assertEqual(consent.status_code, 200)
        form_parser = HiddenInputParser()
        form_parser.feed(consent.content.decode())
        self.assertEqual(
            form_parser.form_action,
            f"/o/authorize/?{urlencode(authorization)}",
        )
        self.assertEqual(
            {
                key: form_parser.values.get(key)
                for key in ("redirect_uri", "scope", "client_id", "response_type")
            },
            {
                "redirect_uri": authorization["redirect_uri"],
                "scope": authorization["scope"],
                "client_id": application.client_id,
                "response_type": "code",
            },
        )
        failed_approval = self.client.post(
            form_parser.form_action,
            {"allow": "true"},
        )
        self.assertEqual(failed_approval.status_code, 200)
        self.assertContains(
            failed_approval,
            "A jóváhagyási kérés adatai nem voltak érvényesek.",
        )
        recovery_parser = HiddenInputParser()
        recovery_parser.feed(failed_approval.content.decode())
        self.assertEqual(recovery_parser.form_action, form_parser.form_action)
        self.assertEqual(
            {
                key: recovery_parser.values.get(key)
                for key in (
                    "redirect_uri",
                    "scope",
                    "client_id",
                    "response_type",
                    "state",
                    "nonce",
                    "code_challenge",
                    "code_challenge_method",
                )
            },
            {
                key: form_parser.values[key]
                for key in (
                    "redirect_uri",
                    "scope",
                    "client_id",
                    "response_type",
                    "state",
                    "nonce",
                    "code_challenge",
                    "code_challenge_method",
                )
            },
        )
        approval = self.client.post(
            recovery_parser.form_action,
            {**recovery_parser.values, "allow": "true"},
        )
        self.assertEqual(approval.status_code, 302)
        authorization_code = parse_qs(urlparse(approval["Location"]).query)["code"][0]

        token_response = self.client.post(
            "/o/token/",
            {
                "grant_type": "authorization_code",
                "code": authorization_code,
                "redirect_uri": authorization["redirect_uri"],
                "client_id": application.client_id,
                "code_verifier": verifier,
            },
        )
        self.assertEqual(token_response.status_code, 200, token_response.content)
        body = token_response.json()
        self.assertIn("access_token", body)
        self.assertIn("id_token", body)

        signed_id_token = JWT(key=application.jwk_key, jwt=body["id_token"])
        claims = json.loads(signed_id_token.claims)
        self.assertEqual(claims["aud"], application.client_id)
        self.assertEqual(claims["nonce"], "test-nonce")
        self.assertTrue(claims["smart_groups"]["student"])
        self.assertEqual(claims["manual_groups"], ["studiosok"])

@override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class ConsentScreenTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="student@example.org",
            password="test-password-123",
        )
        self.application = Application.objects.create(
            name="Igazoláskezelő",
            user=self.user,
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://client.example/callback",
            algorithm=Application.RS256_ALGORITHM,
        )
        self.authorize_url = "/o/authorize/?" + urlencode(
            {
                "response_type": "code",
                "client_id": self.application.client_id,
                "redirect_uri": "https://client.example/callback",
                "scope": "openid profile email groups",
                "state": "s",
                "nonce": "n",
                "code_challenge": "c" * 43,
                "code_challenge_method": "S256",
            }
        )
        self.client.force_login(self.user)

    def test_consent_screen_shows_app_profile_and_hungarian_scopes(self):
        ApplicationProfile.objects.create(
            application=self.application,
            developer="Balla Botond",
            short_description="Az F-tagozat Igazoláskezelő webappja",
            logo="app-logos/igazolas.png",
        )

        response = self.client.get(self.authorize_url)

        self.assertContains(response, "Igazoláskezelő")
        self.assertContains(response, "Az F-tagozat Igazoláskezelő webappja")
        self.assertContains(response, "Balla Botond")
        self.assertContains(response, "/media/app-logos/igazolas.png")
        for title in ("Személyazonosítás", "Alapadatok", "E-mail-cím", "Szerepkör és iskolai csoportok"):
            self.assertContains(response, title)
        self.assertNotContains(response, "Telefonszám")

    def test_consent_screen_works_without_app_profile(self):
        response = self.client.get(self.authorize_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Igazoláskezelő")
        self.assertNotContains(response, "Fejlesztő:")

    def test_pages_are_dark_by_default(self):
        self.client.logout()

        response = self.client.get("/login/")

        self.assertContains(response, 'data-theme="dark"')

    def test_unknown_scope_gets_a_generic_hungarian_description(self):
        details = describe_scopes(["openid", "custom"])

        self.assertEqual(details[0]["title"], "Személyazonosítás")
        self.assertEqual(details[1]["title"], "custom")
        self.assertIn("Az alkalmazás", details[1]["description"])


def _png_upload(name="logo.png", size=(64, 64), fmt="PNG"):
    buffer = BytesIO()
    Image.new("RGB", size, (168, 110, 67)).save(buffer, format=fmt)
    content_type = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif"}[fmt]
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class DashboardTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        media = override_settings(MEDIA_ROOT=self.media_root)
        media.enable()
        self.addCleanup(media.disable)

        self.user = CustomUser.objects.create_user(
            email="student@example.org",
            password="old-password-123!x",
            first_name="Anna",
            last_name="Minta",
        )
        self.other = CustomUser.objects.create_user(
            email="other@example.org", password="other-password-123!x"
        )
        self.client.force_login(self.user)

    def _create_application(self, user, **overrides):
        values = {
            "name": "Teszt app",
            "user": user,
            "client_type": Application.CLIENT_CONFIDENTIAL,
            "authorization_grant_type": Application.GRANT_AUTHORIZATION_CODE,
            "redirect_uris": "https://client.example/callback",
            "algorithm": Application.RS256_ALGORITHM,
        }
        values.update(overrides)
        return Application.objects.create(**values)

    def _app_post(self, **overrides):
        data = {
            "name": "Új app",
            "short_description": "Egy rövid leírás",
            "developer": "Fejlesztő Feri",
            "client_type": Application.CLIENT_CONFIDENTIAL,
            "redirect_uris": "https://client.example/callback",
        }
        data.update(overrides)
        return self.client.post("/apps/new/", data)

    def test_dashboard_requires_login(self):
        self.client.logout()

        response = self.client.get("/")

        self.assertRedirects(response, "/login/?next=/", fetch_redirect_response=False)

    def test_profile_shows_all_stored_data_read_only(self):
        self.user.phone = "+36 1 234"
        self.user.save()
        StudentProfile.objects.create(user=self.user, om_id="7000012345")
        school_group = ManualGroup.objects.create(name="Stúdiósok", slug="studiosok")
        self.user.manual_groups.add(school_group)
        circle = Group.objects.create(name="Naplóadminok")
        self.user.groups.add(circle)

        page = self.client.get("/")

        for expected in (
            "student@example.org",
            str(self.user.oidc_subject),
            "7000012345",
            "Minta",
            "Anna",
            "+36 1 234",
            "Iskolai csoportok",
            "Stúdiósok",
            "Jogosultsági körök",
            "Naplóadminok",
        ):
            self.assertContains(page, expected)
        self.assertNotContains(page, "<form method=\"post\" novalidate>")

    def test_personal_data_cannot_be_changed_by_the_user(self):
        response = self.client.post(
            "/",
            {"last_name": "Új", "first_name": "Név", "phone": "123", "email": "hacker@example.org"},
        )

        self.assertEqual(response.status_code, 405)
        self.user.refresh_from_db()
        self.assertEqual((self.user.last_name, self.user.first_name), ("Minta", "Anna"))
        self.assertEqual(self.user.email, "student@example.org")
    def test_password_change_keeps_session_and_requires_current_password(self):
        bad = self.client.post(
            "/security/",
            {
                "old_password": "wrong",
                "new_password1": "brand-new-pass-9!",
                "new_password2": "brand-new-pass-9!",
            },
        )
        self.assertEqual(bad.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("old-password-123!x"))

        good = self.client.post(
            "/security/",
            {
                "old_password": "old-password-123!x",
                "new_password1": "brand-new-pass-9!",
                "new_password2": "brand-new-pass-9!",
            },
        )
        self.assertRedirects(good, "/security/", fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("brand-new-pass-9!"))
        self.assertEqual(self.client.get("/security/").status_code, 200)

    def test_passkey_only_user_can_set_a_password_without_current_one(self):
        self.user.set_unusable_password()
        self.user.save()
        self.client.force_login(self.user)

        response = self.client.post(
            "/security/",
            {"new_password1": "brand-new-pass-9!", "new_password2": "brand-new-pass-9!"},
        )

        self.assertRedirects(response, "/security/", fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("brand-new-pass-9!"))

    def test_password_reset_flow_by_email(self):
        self.client.logout()

        response = self.client.post("/password/reset/", {"email": "STUDENT@example.org"})
        self.assertRedirects(response, "/password/reset/sent/", fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        link = re.search(r"https?://[^/\s]+(/password/reset/\S+)", mail.outbox[0].body).group(1)

        # Django swaps the token for a session-bound URL on the first visit.
        first = self.client.get(link)
        confirm_url = first["Location"] if first.status_code == 302 else link
        self.assertEqual(self.client.get(confirm_url).status_code, 200)
        done = self.client.post(
            confirm_url,
            {"new_password1": "reset-pass-77!ab", "new_password2": "reset-pass-77!ab"},
        )
        self.assertRedirects(done, "/password/reset/complete/", fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("reset-pass-77!ab"))

    def test_password_reset_does_not_reveal_unknown_accounts(self):
        self.client.logout()

        response = self.client.post("/password/reset/", {"email": "nobody@example.org"})

        self.assertRedirects(response, "/password/reset/sent/", fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 0)

    def test_password_reset_works_for_accounts_without_a_password(self):
        self.client.logout()
        self.user.set_unusable_password()
        self.user.save()

        self.client.post("/password/reset/", {"email": self.user.email})

        self.assertEqual(len(mail.outbox), 1)

    def test_registering_an_application_shows_the_secret_once(self):
        response = self._app_post()
        application = Application.objects.get(name="Új app")
        self.assertEqual(response.status_code, 200)

        secret = response.context["new_secret"]
        self.assertTrue(secret)
        self.assertContains(response, secret)
        application.refresh_from_db()
        self.assertNotEqual(application.client_secret, secret)
        self.assertTrue(application.client_secret.startswith("pbkdf2_"))
        self.assertEqual(application.user, self.user)
        self.assertEqual(application.authorization_grant_type, Application.GRANT_AUTHORIZATION_CODE)
        self.assertEqual(application.algorithm, Application.RS256_ALGORITHM)
        self.assertFalse(application.skip_authorization)
        self.assertEqual(application.profile.developer, "Fejlesztő Feri")
        self.assertFalse(application.profile.verified)

        again = self.client.get(f"/apps/{application.pk}/")
        self.assertNotContains(again, secret)

    def test_users_cannot_choose_protocol_settings(self):
        self._app_post(
            authorization_grant_type=Application.GRANT_PASSWORD,
            skip_authorization="on",
            algorithm="HS256",
        )

        application = Application.objects.get(name="Új app")
        self.assertEqual(application.authorization_grant_type, Application.GRANT_AUTHORIZATION_CODE)
        self.assertFalse(application.skip_authorization)
        self.assertEqual(application.algorithm, Application.RS256_ALGORITHM)

    def test_staff_registered_applications_are_verified(self):
        self.user.is_staff = True
        self.user.save()

        self._app_post()

        self.assertTrue(Application.objects.get(name="Új app").profile.verified)

    def test_insecure_or_invalid_redirect_uris_are_rejected(self):
        production_like = {**settings.OAUTH2_PROVIDER, "ALLOWED_REDIRECT_URI_SCHEMES": ["https"]}
        with self.settings(OAUTH2_PROVIDER=production_like):
            for uri in ("http://evil.example/cb", "javascript:alert(1)", "not a uri"):
                response = self._app_post(redirect_uris=uri)
                self.assertEqual(response.status_code, 200, uri)
                self.assertFalse(Application.objects.filter(name="Új app").exists(), uri)

    def test_application_count_is_limited_for_regular_users(self):
        from .dashboard_views import MAX_APPLICATIONS_PER_USER

        for index in range(MAX_APPLICATIONS_PER_USER):
            self._create_application(self.user, name=f"App {index}")

        response = self._app_post()

        self.assertRedirects(response, "/apps/", fetch_redirect_response=False)
        self.assertFalse(Application.objects.filter(name="Új app").exists())

    def test_logo_upload_accepts_png_and_rejects_other_formats(self):
        good = self._app_post(logo=_png_upload())
        self.assertEqual(good.status_code, 200)
        application = Application.objects.get(name="Új app")
        self.assertTrue(application.profile.logo.name.startswith("app-logos/"))

        gif = self._app_post(name="Gif app", logo=_png_upload("logo.gif", fmt="GIF"))
        svg = self._app_post(
            name="Svg app",
            logo=SimpleUploadedFile(
                "logo.svg",
                b"<svg xmlns='http://www.w3.org/2000/svg'/>",
                content_type="image/svg+xml",
            ),
        )
        self.assertFalse(Application.objects.filter(name__in=["Gif app", "Svg app"]).exists())
        self.assertEqual((gif.status_code, svg.status_code), (200, 200))

    def test_users_cannot_access_other_peoples_applications(self):
        theirs = self._create_application(self.other)

        for method, url in (
            ("get", f"/apps/{theirs.pk}/"),
            ("get", f"/apps/{theirs.pk}/edit/"),
            ("post", f"/apps/{theirs.pk}/edit/"),
            ("post", f"/apps/{theirs.pk}/rotate-secret/"),
            ("post", f"/apps/{theirs.pk}/delete/"),
        ):
            self.assertEqual(getattr(self.client, method)(url).status_code, 404, url)
        self.assertTrue(Application.objects.filter(pk=theirs.pk).exists())

    def test_rotating_and_deleting_an_application(self):
        application = self._create_application(self.user)
        old_hash = Application.objects.get(pk=application.pk).client_secret

        rotated = self.client.post(f"/apps/{application.pk}/rotate-secret/")
        self.assertEqual(rotated.status_code, 200)
        self.assertTrue(rotated.context["new_secret"])
        self.assertNotEqual(Application.objects.get(pk=application.pk).client_secret, old_hash)

        deleted = self.client.post(f"/apps/{application.pk}/delete/")
        self.assertRedirects(deleted, "/apps/", fetch_redirect_response=False)
        self.assertFalse(Application.objects.filter(pk=application.pk).exists())

    def test_application_management_views_of_the_toolkit_are_not_exposed(self):
        for url in ("/o/applications/", "/o/applications/register/", "/o/authorized_tokens/"):
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def _grant(self, user, application, scope="openid email"):
        token = AccessToken.objects.create(
            user=user,
            application=application,
            token=f"token-{user.pk}-{application.pk}",
            expires=timezone.now() + timedelta(hours=1),
            scope=scope,
        )
        RefreshToken.objects.create(
            user=user,
            application=application,
            token=f"refresh-{user.pk}-{application.pk}",
            access_token=token,
        )
        return token

    def test_grants_are_listed_and_can_be_revoked(self):
        application = self._create_application(self.other, name="Külső app")
        self._grant(self.user, application, "openid email groups")
        self._grant(self.other, application)

        page = self.client.get("/grants/")
        self.assertContains(page, "Külső app")
        self.assertContains(page, "E-mail-cím")
        self.assertContains(page, "Szerepkör és iskolai csoportok")

        response = self.client.post(f"/grants/{application.pk}/revoke/")

        self.assertRedirects(response, "/grants/", fetch_redirect_response=False)
        self.assertFalse(AccessToken.objects.filter(user=self.user).exists())
        self.assertFalse(RefreshToken.objects.filter(user=self.user).exists())
        self.assertTrue(AccessToken.objects.filter(user=self.other).exists())
        self.assertEqual(self.client.get("/grants/").context["grants"], [])

    def test_consent_screen_warns_about_unverified_applications(self):
        application = self._create_application(self.other, client_type=Application.CLIENT_PUBLIC)
        query = urlencode(
            {
                "response_type": "code",
                "client_id": application.client_id,
                "redirect_uri": "https://client.example/callback",
                "scope": "openid",
                "state": "s",
                "code_challenge": "c" * 43,
                "code_challenge_method": "S256",
            }
        )

        unverified = self.client.get(f"/o/authorize/?{query}")
        self.assertContains(unverified, "nem ellenőrizte az iskola")

        ApplicationProfile.objects.create(
            application=application, developer="X", short_description="Y", verified=True
        )
        verified = self.client.get(f"/o/authorize/?{query}")
        self.assertNotContains(verified, "nem ellenőrizte az iskola")
        self.assertContains(verified, "ellenőrzött alkalmazás")


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class GlobalConfigTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_superuser(
            email="admin@example.org", password="admin-password-123!x"
        )
        self.client.force_login(self.admin)

    def test_migration_creates_the_single_record(self):
        self.assertEqual(GlobalConfig.objects.count(), 1)
        self.assertEqual(GlobalConfig.get_solo().pk, 1)
        self.assertTrue(GlobalConfig.get_solo().promote_passkey)

    def test_only_one_record_can_exist_and_it_cannot_be_deleted(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            GlobalConfig.objects.create(promote_passkey=False)

        # Saving a new instance updates the single row instead of adding another.
        GlobalConfig(promote_passkey=False).save()

        self.assertEqual(GlobalConfig.objects.count(), 1)
        self.assertFalse(GlobalConfig.get_solo().promote_passkey)

        GlobalConfig.get_solo().delete()
        self.assertEqual(GlobalConfig.objects.count(), 1)

    def test_admin_edits_the_record_but_cannot_add_or_delete(self):
        form = self.client.get("/admin/api/globalconfig/", follow=True)
        self.assertEqual(form.status_code, 200)
        self.assertContains(form, "promote_passkey")

        self.assertEqual(self.client.get("/admin/api/globalconfig/add/").status_code, 403)
        self.assertEqual(self.client.post("/admin/api/globalconfig/1/delete/").status_code, 403)

        self.client.post("/admin/api/globalconfig/1/change/", {"_save": "Mentés"})
        self.assertFalse(GlobalConfig.get_solo().promote_passkey)
        self.assertEqual(GlobalConfig.objects.count(), 1)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class PasskeyPromoTests(TestCase):
    PASSWORD = "promo-password-123!x"

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="student@example.org", password=self.PASSWORD
        )

    def _password_login(self, next_url=""):
        return self.client.post(
            "/login/password/",
            {"email": self.user.email, "password": self.PASSWORD, "next": next_url},
        )

    def test_password_login_offers_a_passkey_and_later_continues_to_the_destination(self):
        response = self._password_login("/apps/")

        self.assertRedirects(response, "/login/passkey/offer/", fetch_redirect_response=False)
        offer = self.client.get("/login/passkey/offer/")
        self.assertContains(offer, "Jelkulcs beállítása")
        self.assertContains(offer, "Majd legközelebb")
        self.assertNotContains(offer, 'id="passkey-name"')

        later = self.client.post("/login/passkey/offer/")
        self.assertRedirects(later, "/apps/", fetch_redirect_response=False)
        self.assertRedirects(
            self.client.get("/login/passkey/offer/"), "/", fetch_redirect_response=False
        )

    def test_offer_is_shown_again_at_the_next_password_login(self):
        self._password_login()
        self.client.post("/login/passkey/offer/")
        self.client.post("/logout/")

        self.assertRedirects(self._password_login(), "/login/passkey/offer/", fetch_redirect_response=False)

    def test_external_destination_is_never_followed(self):
        self._password_login("https://attacker.invalid/")

        later = self.client.post("/login/passkey/offer/")

        self.assertRedirects(later, "/", fetch_redirect_response=False)

    def test_no_offer_when_disabled_in_the_global_config(self):
        config = GlobalConfig.get_solo()
        config.promote_passkey = False
        config.save()

        self.assertRedirects(self._password_login(), "/", fetch_redirect_response=False)

    def _add_passkey(self, user, tag=b"k"):
        return Passkey.objects.create(user=user, credential_id=b"cred-" + tag, public_key=b"key")

    def _remember_this_device(self):
        self._password_login()
        return self.client.post("/login/passkey/offer/", {"device_ready": "1"})

    def test_first_offer_is_the_full_pitch_without_a_device_shortcut(self):
        self._password_login()

        offer = self.client.get("/login/passkey/offer/")

        self.assertContains(offer, "Lépj be gyorsabban")
        self.assertContains(offer, "Adathalászat ellen is véd")
        self.assertNotContains(offer, "Ezen az eszközön már van jelkulcsom")

    def test_users_with_passkeys_are_offered_one_for_a_new_device(self):
        self._add_passkey(self.user)

        response = self._password_login("/apps/")

        self.assertRedirects(response, "/login/passkey/offer/", fetch_redirect_response=False)
        offer = self.client.get("/login/passkey/offer/")
        self.assertContains(offer, "Jelkulcs létrehozása ezen az eszközön")
        self.assertContains(offer, "Ezen az eszközön már van jelkulcsom")
        self.assertNotContains(offer, "Adathalászat ellen is véd")
        self.assertRedirects(
            self.client.post("/login/passkey/offer/"), "/apps/", fetch_redirect_response=False
        )

    def test_declaring_the_device_ready_stops_the_offer_on_this_device(self):
        self._add_passkey(self.user)

        response = self._remember_this_device()

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertIn("szlg_jelkulcs", self.client.cookies)
        self.client.post("/logout/")
        self.assertRedirects(self._password_login(), "/", fetch_redirect_response=False)

    def test_device_memory_is_per_user(self):
        other = CustomUser.objects.create_user(email="other@example.org", password=self.PASSWORD)
        self._add_passkey(self.user, b"a")
        self._add_passkey(other, b"b")
        self._remember_this_device()
        self.client.post("/logout/")

        response = self.client.post(
            "/login/password/", {"email": other.email, "password": self.PASSWORD}
        )

        self.assertRedirects(response, "/login/passkey/offer/", fetch_redirect_response=False)

    def test_tampered_device_cookie_is_ignored(self):
        self._add_passkey(self.user)
        self.client.cookies["szlg_jelkulcs"] = str(self.user.pk)

        self.assertRedirects(
            self._password_login(), "/login/passkey/offer/", fetch_redirect_response=False
        )

    def test_successful_passkey_login_marks_the_device(self):
        self._add_passkey(self.user)
        with patch("api.web_views.verify_authentication", return_value=self.user):
            self.client.post(
                "/login/passkey/verify/",
                data=json.dumps({"challenge_id": "c", "credential": {}}),
                content_type="application/json",
            )
        self.assertIn("szlg_jelkulcs", self.client.cookies)
        self.client.post("/logout/")

        self.assertRedirects(self._password_login(), "/", fetch_redirect_response=False)

    def test_registering_a_passkey_marks_the_device(self):
        self._password_login()
        with patch("api.web_views.verify_registration"):
            self.client.post(
                "/account/passkeys/register/verify/",
                data=json.dumps({"credential": {}, "name": "Chrome · Windows"}),
                content_type="application/json",
            )

        self.assertIn("szlg_jelkulcs", self.client.cookies)
    def test_passkey_login_never_triggers_the_offer(self):
        with patch("api.web_views.verify_authentication", return_value=self.user):
            response = self.client.post(
                "/login/passkey/verify/",
                data=json.dumps({"challenge_id": "c", "credential": {}, "next": ""}),
                content_type="application/json",
            )

        self.assertEqual(response.json()["redirect"], "/")
        self.assertNotIn("passkey_promo_next", self.client.session)

    def test_offer_without_a_pending_password_login_goes_to_the_dashboard(self):
        self.client.force_login(self.user)

        self.assertRedirects(
            self.client.get("/login/passkey/offer/"), "/", fetch_redirect_response=False
        )

    def test_offer_requires_login(self):
        self.assertEqual(self.client.get("/login/passkey/offer/").status_code, 302)
        self.assertIn("/login/", self.client.get("/login/passkey/offer/")["Location"])

    def test_registering_from_the_offer_returns_to_the_destination_without_a_name(self):
        self._password_login("/grants/")

        with patch("api.web_views.verify_registration") as register:
            response = self.client.post(
                "/account/passkeys/register/verify/",
                data=json.dumps({"credential": {}, "name": "Chrome · Windows", "promo": True}),
                content_type="application/json",
            )

        self.assertEqual(response.json(), {"redirect": "/grants/"})
        register.assert_called_once()
        self.assertEqual(register.call_args.args[2], "Chrome · Windows")
        self.assertNotIn("passkey_promo_next", self.client.session)

    def test_registering_from_the_security_page_stays_on_the_security_page(self):
        self._password_login("/grants/")

        with patch("api.web_views.verify_registration"):
            response = self.client.post(
                "/account/passkeys/register/verify/",
                data=json.dumps({"credential": {}, "name": "Saját eszköz"}),
                content_type="application/json",
            )

        self.assertEqual(response.json(), {"redirect": "/security/"})
