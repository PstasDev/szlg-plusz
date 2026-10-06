import base64
import hashlib
import json
import manage
from html.parser import HTMLParser
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlparse

from django.test import TestCase, override_settings
from oauth2_provider.models import Application
from jwcrypto.jwt import JWT

from .auth_challenges import consume_challenge
from .models import CustomUser, ManualGroup, StudentProfile
from .oauth import SZLGPlusOAuth2Validator


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
        StudentProfile.objects.create(user=self.user, student_number="12345")
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

        self.assertRedirects(response, "/account/", fetch_redirect_response=False)
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
