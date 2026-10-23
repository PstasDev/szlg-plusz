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
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from oauth2_provider.models import AccessToken, Application, RefreshToken
from jwcrypto.jwt import JWT
from PIL import Image

from .auth_challenges import consume_challenge
from .models import (
    ApplicationProfile,
    CustomUser,
    GroupMailboxAssociation,
    GlobalConfig,
    InstitutionalRole,
    ManualGroup,
    Passkey,
    SchoolClass,
    StudentProfile,
    Tagozat,
    TeacherProfile,
    UserAppConnection,
    email_info,
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
        self.seen_form = False
        self.in_first_form = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "form":
            if not self.seen_form:
                self.form_action = attributes.get("action")
                self.seen_form = True
                self.in_first_form = True
            else:
                self.in_first_form = False
            return
        if tag != "input" or not self.in_first_form:
            return
        if attributes.get("type") == "hidden":
            self.values[attributes["name"]] = attributes.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.in_first_form = False


class IdentityModelTests(TestCase):
    def setUp(self):
        config = GlobalConfig.get_solo()
        config.school_domain = "@example.org"
        config.save()
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
            {
                "student": True,
                "teacher": False,
                "staff": False,
                "part_time_student": False,
                "computer_test_account": False,
                "group_email": False,
                "teacher_or_school_employee": False,
            },
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

    def test_email_patterns_are_parsed_from_the_local_part(self):
        with patch("api.models.get_school_domain", return_value="@szlgbp.hu"):
            self.assertTrue(email_info("titkarsag@szlgbp.hu").is_group_email)
            self.assertFalse(email_info("minta.anna@szlgbp.hu").is_group_email)
            self.assertTrue(email_info("minta.anna.23af@szlgbp.hu").is_part_time_student)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class DirectoryTests(TestCase):
    def setUp(self):
        config = GlobalConfig.get_solo()
        config.school_domain = "@school.test"
        config.save()
        self.student = CustomUser.objects.create_user(
            email="anna.23f@school.test", first_name="Anna", last_name="Minta"
        )
        self.external = CustomUser.objects.create_user(
            email="bela@outside.test", first_name="Béla", last_name="Külső"
        )
        self.mailbox = CustomUser.objects.create_user(
            email="nappali.diakok@school.test",
            first_name="Nappali diákok",
            is_group_mailbox=True,
        )
        self.tagozat = Tagozat.objects.create(name="Nappali", slug="nappali")
        StudentProfile.objects.create(
            user=self.student, kezdes_eve=2023, szekcio="F", tagozat=self.tagozat
        )
        self.client.force_login(self.student)

    def test_people_search_is_school_domain_limited_and_groups_mailboxes_last(self):
        response = self.client.get("/dashboard/?q=a")
        self.assertNotContains(response, "Anna Minta")

        response = self.client.get("/dashboard/?q=Anna")
        self.assertContains(response, "Minta Anna")
        self.assertContains(response, self.student.email)
        self.assertNotContains(response, self.external.email)
        self.assertNotContains(response, self.mailbox.email)

        response = self.client.get("/dashboard/?q=diakok")
        self.assertContains(response, "Csoportos postafiókok")
        self.assertContains(response, self.mailbox.email)
        self.assertNotContains(response, self.external.email)

    def test_staff_can_search_accounts_outside_school_domain(self):
        self.student.is_staff = True
        self.student.save(update_fields=["is_staff"])

        response = self.client.get("/dashboard/?q=Külső")

        self.assertContains(response, self.external.email)

    def test_person_detail_shows_only_directory_basics_and_marks_mailboxes(self):
        response = self.client.get(f"/dashboard/people/{self.student.pk}/")
        self.assertContains(response, "Minta Anna")
        self.assertContains(response, self.student.student_profile.osztaly)
        self.assertContains(response, "Nappali")
        self.assertContains(response, self.student.email)
        self.assertNotContains(response, "OM azonosító")

        mailbox_page = self.client.get(f"/dashboard/people/{self.mailbox.pk}/")
        self.assertContains(mailbox_page, "Csoportos postafiók")
        self.assertFalse(self.mailbox.is_teacher_or_school_employee)

    def test_normal_users_cannot_open_an_out_of_domain_person_directly(self):
        response = self.client.get(f"/dashboard/people/{self.external.pk}/")
        self.assertEqual(response.status_code, 404)

    def test_any_user_can_create_a_private_group_but_does_not_join_automatically(self):
        response = self.client.post(
            "/dashboard/groups/new/",
            {"name": "Foci csapat", "description": "Közösségi csoport"},
        )

        self.assertEqual(response.status_code, 302)
        group = ManualGroup.objects.get(name="Foci csapat")
        self.assertFalse(group.is_public)
        self.assertEqual(group.created_by, self.student)
        self.assertTrue(group.managers.filter(pk=self.student.pk).exists())
        self.assertFalse(group.members.filter(pk=self.student.pk).exists())

    def test_only_group_managers_can_edit_members_and_group_details(self):
        group = ManualGroup.objects.create(
            name="Stúdiósok", slug="studiosok", created_by=self.external
        )
        group.managers.add(self.external)

        response = self.client.post(
            f"/dashboard/groups/{group.directory_key}/",
            {"name": "Átnevezett", "description": "", "is_public": "on"},
        )

        self.assertEqual(response.status_code, 403)
        group.refresh_from_db()
        self.assertEqual(group.name, "Stúdiósok")

    def test_nonpublic_groups_are_hidden_from_browse_but_searchable(self):
        public = ManualGroup.objects.create(
            name="Nyilvános klub", slug="nyilvanos-klub", is_public=True
        )
        private = ManualGroup.objects.create(
            name="Specifikus csapat", slug="specifikus-csapat", is_public=False
        )

        browse = self.client.get("/dashboard/groups/")
        self.assertContains(browse, public.name)
        self.assertNotContains(browse, private.name)
        search = self.client.get("/dashboard/groups/?q=Specifikus")
        self.assertContains(search, private.name)

    def test_group_detail_lists_members_and_gmail_draft_recipients(self):
        group = ManualGroup.objects.create(
            name="Nappalisok", slug="nappalisok", is_public=True
        )
        group.members.add(self.student)
        GroupMailboxAssociation.objects.create(
            mailbox=self.mailbox, group_key=group.directory_key
        )

        response = self.client.get(f"/dashboard/groups/{group.directory_key}/")

        self.assertContains(response, self.student.email)
        self.assertContains(response, "mail.google.com/mail/")
        self.assertContains(response, self.mailbox.email)

    def test_school_groups_and_application_group_policy_appear_in_oidc_claims(self):
        group = ManualGroup.objects.create(name="Stúdiósok", slug="studiosok")
        group.members.add(self.student)
        permission_circle = Group.objects.create(name="Naplóadminok")
        self.student.groups.add(permission_circle)
        role = InstitutionalRole.objects.get(slug="intezmenyvezeto")
        role.members.add(self.student)
        school_class, _ = SchoolClass.objects.get_or_create(
            start_year=2023, section="F"
        )
        application = Application.objects.create(
            name="Címtár teszt app",
            user=self.external,
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://client.example/callback",
            algorithm=Application.RS256_ALGORITHM,
        )
        ApplicationProfile.objects.create(
            application=application,
            developer="SZLG+",
            short_description="Teszt",
            required_group_keys=["osztaly-2023-f-diakok"],
        )
        request = SimpleNamespace(
            user=self.student,
            client_id=application.client_id,
            scopes=["openid", "groups"],
        )

        claims = SZLGPlusOAuth2Validator().get_oidc_claims(None, None, request)

        self.assertIn(group.directory_key, claims["school_groups"])
        self.assertIn(f"tagozat-{self.tagozat.slug}", claims["school_groups"])
        self.assertIn("osztaly-2023-f-diakok", claims["school_groups"])
        self.assertIn("szerepkor-intezmenyvezeto", claims["school_groups"])
        self.assertNotIn("staff", claims["school_groups"])
        self.assertNotIn(permission_circle.name, claims["school_groups"])
        self.assertTrue(claims["application_group_access"])
        self.assertEqual(
            claims["application_required_groups"],
            ["osztaly-2023-f-diakok"],
        )

        application.profile.required_group_keys = ["smart-teacher"]
        application.profile.save(update_fields=["required_group_keys"])
        denied_claims = SZLGPlusOAuth2Validator().get_oidc_claims(
            None, None, request
        )
        self.assertFalse(denied_claims["application_group_access"])

    def test_staff_setup_page_is_separate_from_permission_groups(self):
        self.assertEqual(self.client.get("/dashboard/directory/setup/").status_code, 403)
        self.student.is_staff = True
        self.student.save(update_fields=["is_staff"])

        response = self.client.get("/dashboard/directory/setup/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Címtár teendők")
        self.assertContains(response, "Intézményvezető")

    def test_staff_can_mark_and_link_an_existing_group_mailbox(self):
        self.student.is_staff = True
        self.student.save(update_fields=["is_staff"])

        marked = self.client.post(
            "/dashboard/directory/setup/",
            {"action": "mark-mailbox", "mailbox": self.external.pk},
        )
        self.assertEqual(marked.status_code, 302)
        self.external.refresh_from_db()
        self.assertTrue(self.external.is_group_mailbox)

        linked = self.client.post(
            "/dashboard/directory/setup/",
            {
                "action": "link-mailbox",
                "mailbox": self.external.pk,
                "group_key": "smart-student",
            },
        )
        self.assertEqual(linked.status_code, 302)
        self.assertTrue(
            GroupMailboxAssociation.objects.filter(
                mailbox=self.external, group_key="smart-student"
            ).exists()
        )


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class SchoolFeatureAccessTests(TestCase):
    def setUp(self):
        config = GlobalConfig.get_solo()
        config.school_domain = "@school.test"
        config.save()
        self.school_user = CustomUser.objects.create_user(
            email="diak@school.test", first_name="Iskolai", last_name="Felhasználó"
        )
        self.external_user = CustomUser.objects.create_user(
            email="kulso@example.org", first_name="Külső", last_name="Felhasználó"
        )
        self.group = ManualGroup.objects.create(
            name="Belső csoport", slug="belso-csoport"
        )

    def test_external_users_can_manage_their_account_but_not_school_features(self):
        self.client.force_login(self.external_user)

        home = self.client.get("/dashboard/?q=Iskolai")
        self.assertEqual(home.status_code, 200)
        self.assertContains(home, self.external_user.email)
        self.assertContains(home, "Saját fiók")
        self.assertNotContains(home, "Kit keresel?")
        self.assertNotContains(home, 'href="/dashboard/schedule/"')
        self.assertNotContains(home, 'href="/dashboard/groups/"')
        self.assertNotContains(home, 'href="/dashboard/map/"')
        self.assertNotContains(home, self.school_user.email)

        forbidden_paths = (
            "/dashboard/groups/",
            "/dashboard/groups/?q=Belső",
            "/dashboard/groups/new/",
            f"/dashboard/groups/{self.group.directory_key}/",
            f"/dashboard/people/{self.school_user.pk}/",
            "/dashboard/schedule/",
            "/dashboard/map/",
        )
        for path in forbidden_paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)

        for path in ("/account/profile/", "/security/", "/apps/", "/grants/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

        app_form = self.client.get("/apps/new/")
        self.assertNotContains(app_form, "Alkalmazáshoz szükséges csoportok")

        claims = SZLGPlusOAuth2Validator().get_oidc_claims(
            None,
            None,
            SimpleNamespace(user=self.external_user, scopes=["openid", "groups"]),
        )
        self.assertEqual(claims["school_groups"], [])
        self.assertEqual(claims["manual_groups"], [])
        self.assertFalse(any(claims["smart_groups"].values()))

    def test_school_users_and_staff_can_access_school_features(self):
        for user in (self.school_user, self.external_user):
            if user == self.external_user:
                user.is_staff = True
                user.save(update_fields=["is_staff"])
            with self.subTest(user=user.email):
                self.client.force_login(user)
                for path in (
                    "/dashboard/groups/",
                    f"/dashboard/groups/{self.group.directory_key}/",
                    f"/dashboard/people/{self.school_user.pk}/",
                    "/dashboard/schedule/",
                    "/dashboard/map/",
                ):
                    with self.subTest(path=path):
                        self.assertEqual(self.client.get(path).status_code, 200)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class LoginAndOIDCTests(TestCase):
    def setUp(self):
        config = GlobalConfig.get_solo()
        config.school_domain = "@example.org"
        config.save()
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
        self.assertEqual(self.client.session["passkey_promo_next"], "/dashboard/")
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
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class RegistrationTests(TestCase):
    PASSWORD = "Evergreen-Password-47!"

    def setUp(self):
        cache.clear()
        config = GlobalConfig.get_solo()
        config.school_domain = "@szlgbp.hu"
        config.promote_passkey = False
        config.save()

    def _registration_data(self, **overrides):
        values = {
            "email": "external@example.org",
            "first_name": "Anna",
            "last_name": "Minta",
            "password1": self.PASSWORD,
            "password2": self.PASSWORD,
            "privacy_consent": "on",
        }
        values.update(overrides)
        return values

    def test_privacy_policy_is_available_on_landing_login_registration_and_standalone_page(self):
        for path in ("/", "/login/", "/register/", "/adatvedelem/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Adatkezelési Tájékoztató")
                self.assertContains(response, "Kőbányai Szent László Gimnázium")

    def test_registration_requires_policy_consent(self):
        response = self.client.post(
            "/register/", self._registration_data(privacy_consent="")
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(CustomUser.objects.filter(email="external@example.org").exists())
        self.assertContains(response, "hozzájárulok a regisztrációhoz szükséges adatkezeléshez")

    def test_new_account_is_inactive_until_email_confirmation(self):
        response = self.client.post("/register/", self._registration_data())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Megerősítő levelet küldtünk")
        user = CustomUser.objects.get(email="external@example.org")
        self.assertFalse(user.is_active)
        self.assertFalse(user.email_verified)
        self.assertIsNotNone(user.privacy_consent_at)
        self.assertTrue(user.check_password(self.PASSWORD))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [user.email])

        denied = self.client.post(
            "/login/password/", {"email": user.email, "password": self.PASSWORD}
        )
        self.assertEqual(denied.status_code, 401)
        self.assertNotIn("_auth_user_id", self.client.session)

        confirmation_path = re.search(
            r"/email/confirm/([^/\s]+)", mail.outbox[0].body
        ).group(0) + "/"
        preview = self.client.get(confirmation_path)
        self.assertEqual(preview.status_code, 200)
        user.refresh_from_db()
        self.assertFalse(user.is_active, "Opening the link alone must not activate accounts.")

        confirmed = self.client.post(confirmation_path)
        self.assertRedirects(confirmed, "/email/confirmed/", fetch_redirect_response=False)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.email_verified)

        login_response = self.client.post(
            "/login/password/", {"email": user.email, "password": self.PASSWORD}
        )
        self.assertEqual(login_response.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)

    def test_school_domain_registration_is_blocked_and_lists_configured_contacts(self):
        contact = CustomUser.objects.create_user(
            email="admin@example.org", first_name="Attila", last_name="Admin"
        )
        GlobalConfig.get_solo().administrator_contacts.add(contact)

        response = self.client.post(
            "/register/",
            self._registration_data(email="diak.23a@SZLGBP.HU"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Iskolai e-mail-címmel nem lehet önállóan regisztrálni")
        self.assertContains(response, "admin@example.org")
        self.assertFalse(CustomUser.objects.filter(email__iexact="diak.23a@szlgbp.hu").exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_registration_does_not_create_a_duplicate_for_an_existing_user(self):
        existing = CustomUser.objects.create_user(
            email="external@example.org", password=self.PASSWORD
        )

        response = self.client.post(
            "/register/", self._registration_data(email="EXTERNAL@example.org")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ehhez az e-mail-címhez már tartozik fiók")
        self.assertEqual(CustomUser.objects.filter(email__iexact=existing.email).count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_resend_sends_only_for_pending_self_service_registrations(self):
        pending = CustomUser.objects.create_user(
            email="pending@example.org",
            password=self.PASSWORD,
            is_active=False,
            privacy_consent_at=timezone.now(),
        )
        existing = CustomUser.objects.create_user(email="old@example.org", is_active=False)

        response = self.client.post(
            "/email/confirm/resend/", {"email": pending.email}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [pending.email])

        self.client.post("/email/confirm/resend/", {"email": existing.email})
        self.assertEqual(len(mail.outbox), 1)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class ConsentScreenTests(TestCase):
    def setUp(self):
        config = GlobalConfig.get_solo()
        config.school_domain = "@example.org"
        config.save()
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
        for title in ("Személyazonosítás", "Alapadatok", "E-mail-cím", "Iskolai csoportok és szerepek"):
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
        config = GlobalConfig.get_solo()
        config.school_domain = "@example.org"
        config.save()
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

        response = self.client.get("/dashboard/")

        self.assertRedirects(
            response,
            "/login/?next=/dashboard/",
            fetch_redirect_response=False,
        )

    def test_landing_page_and_docs_are_public(self):
        landing = self.client.get("/")
        docs = self.client.get("/docs/")

        self.assertEqual(landing.status_code, 200)
        self.assertContains(landing, "Dashboard megnyitása")
        self.assertContains(landing, "jelkulcsos belépés")
        self.assertEqual(docs.status_code, 200)
        self.assertContains(docs, "Útmutató felhasználóknak")
        self.assertContains(docs, "SZLG+ adminisztrátoroknak")
        self.assertContains(docs, "Alkalmazásfejlesztőknek")
        self.assertContains(docs, "SZLG+ fejlesztőknek")
        for path, title in (
            ("/docs/felhasznalok/", "Útmutató felhasználóknak"),
            ("/docs/adminisztratorok/", "Útmutató SZLG+ adminisztrátoroknak"),
            ("/docs/alkalmazas-fejlesztok/", "Útmutató alkalmazásfejlesztőknek"),
            ("/docs/szlg-fejlesztok/", "Útmutató SZLG+ fejlesztőknek"),
        ):
            with self.subTest(path=path):
                page = self.client.get(path)
                self.assertEqual(page.status_code, 200)
                self.assertContains(page, title)

    def test_dashboard_home_uses_app_launcher(self):
        application = self._create_application(self.other)
        ApplicationProfile.objects.create(
            application=application,
            developer="SZLG+",
            short_description="Ügyintézés",
            launch_url="https://igazolas.example.org/",
        )
        UserAppConnection.objects.create(user=self.user, application=application)

        response = self.client.get("/dashboard/")

        self.assertContains(response, "Teszt app")
        self.assertContains(response, "https://igazolas.example.org/")
        self.assertContains(response, "Kit keresel?")
        self.assertContains(response, "Órarend")

    def test_profile_shows_all_stored_data_read_only(self):
        self.user.phone = "+36 1 234"
        self.user.save()
        StudentProfile.objects.create(user=self.user, om_id="7000012345")
        school_group = ManualGroup.objects.create(name="Stúdiósok", slug="studiosok")
        self.user.manual_groups.add(school_group)
        circle = Group.objects.create(name="Naplóadminok")
        self.user.groups.add(circle)

        page = self.client.get("/account/profile/")

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
            "/account/profile/",
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

    def test_application_owner_can_configure_required_school_groups(self):
        response = self._app_post(required_group_keys=["smart-student"])

        self.assertEqual(response.status_code, 200)
        application = Application.objects.get(name="Új app")
        self.assertEqual(application.profile.required_group_keys, ["smart-student"])
        self.assertContains(response, "Diákok")

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
        self.assertContains(page, "Iskolai csoportok és szerepek")

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

    def test_email_classification_uses_configured_school_domain(self):
        config = GlobalConfig.get_solo()
        config.school_domain = "@example.org"
        config.save()

        self.assertTrue(email_info("student@example.org").is_in_school_domain)
        self.assertFalse(email_info("student@szlgbp.hu").is_in_school_domain)

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

    def test_admin_can_select_public_szlg_contacts(self):
        contact = CustomUser.objects.create_user(
            email="contact@example.org", first_name="Kapcsolat"
        )

        response = self.client.post(
            "/admin/api/globalconfig/1/change/",
            {
                "_save": "Mentés",
                "promote_passkey": "on",
                "school_domain": "@szlgbp.hu",
                "administrator_contacts": [str(contact.pk)],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertQuerySetEqual(
            GlobalConfig.get_solo().administrator_contacts.all(), [contact]
        )


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class PasskeyPromoTests(TestCase):
    PASSWORD = "promo-password-123!x"

    def setUp(self):
        cache.clear()  # the login rate limit is keyed by e-mail and shared across tests
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
            self.client.get("/login/passkey/offer/"), "/dashboard/", fetch_redirect_response=False
        )

    def test_offer_is_shown_again_at_the_next_password_login(self):
        self._password_login()
        self.client.post("/login/passkey/offer/")
        self.client.post("/logout/")

        self.assertRedirects(self._password_login(), "/login/passkey/offer/", fetch_redirect_response=False)

    def test_external_destination_is_never_followed(self):
        self._password_login("https://attacker.invalid/")

        later = self.client.post("/login/passkey/offer/")

        self.assertRedirects(later, "/dashboard/", fetch_redirect_response=False)

    def test_no_offer_when_disabled_in_the_global_config(self):
        config = GlobalConfig.get_solo()
        config.promote_passkey = False
        config.save()

        self.assertRedirects(self._password_login(), "/dashboard/", fetch_redirect_response=False)

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

        self.assertRedirects(response, "/dashboard/", fetch_redirect_response=False)
        self.assertIn("szlg_jelkulcs", self.client.cookies)
        self.client.post("/logout/")
        self.assertRedirects(self._password_login(), "/dashboard/", fetch_redirect_response=False)

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

        self.assertRedirects(self._password_login(), "/dashboard/", fetch_redirect_response=False)

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

        self.assertEqual(response.json()["redirect"], "/dashboard/")
        self.assertNotIn("passkey_promo_next", self.client.session)

    def test_offer_without_a_pending_password_login_goes_to_the_dashboard(self):
        self.client.force_login(self.user)

        self.assertRedirects(
            self.client.get("/login/passkey/offer/"), "/dashboard/", fetch_redirect_response=False
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


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class ConsentRerenderTests(TestCase):
    """The approval page after a rejected POST must still show the application."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(email="student@example.org", password="x-Pass-123456!")
        self.application = Application.objects.create(
            name="Igazoláskezelő",
            user=self.user,
            client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://client.example/callback",
            algorithm=Application.RS256_ALGORITHM,
        )
        ApplicationProfile.objects.create(
            application=self.application,
            developer="Balla Botond",
            short_description="Az F-tagozat webappja",
            verified=True,
        )
        self.client.force_login(self.user)

    def test_rejected_approval_keeps_application_details_and_verified_state(self):
        with self.assertLogs("szlg_plusz.oidc_urls", level="WARNING") as logs:
            response = self.client.post(
                "/o/authorize/",
                {"allow": "true", "client_id": self.application.client_id, "scope": "openid email"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Igazoláskezelő")
        self.assertContains(response, "Balla Botond")
        self.assertContains(response, "Az F-tagozat webappja")
        self.assertContains(response, "ellenőrzött alkalmazás")
        self.assertNotContains(response, "nem ellenőrizte az iskola")
        self.assertContains(response, "A jóváhagyási kérés adatai nem voltak érvényesek.")
        self.assertContains(response, "E-mail-cím")
        self.assertIn("redirect_uri", logs.output[0])
        self.assertNotIn(self.application.client_id, logs.output[0])

    def test_unknown_client_shows_no_verification_notice(self):
        response = self.client.post("/o/authorize/", {"allow": "true", "client_id": "does-not-exist"})

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "nem ellenőrizte az iskola")
        self.assertNotContains(response, "ellenőrzött alkalmazás")


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class CsrfFailurePageTests(TestCase):
    def test_failed_csrf_check_shows_a_readable_page_with_the_reason(self):
        client = Client(enforce_csrf_checks=True)

        with self.assertLogs("api.web_views", level="WARNING"):
            response = client.post("/login/password/", {"email": "a@example.org", "password": "x"})

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "A kérés nem teljesíthető", status_code=403)
        self.assertContains(response, "CSRF", status_code=403)


@override_settings(SECURE_SSL_REDIRECT=False)
class OidcIssuerTests(TestCase):
    def test_discovery_advertises_the_configured_https_issuer_even_over_http(self):
        provider = {**settings.OAUTH2_PROVIDER, "OIDC_ISS_ENDPOINT": "https://sso.example.test/o"}

        with self.settings(OAUTH2_PROVIDER=provider):
            document = self.client.get("/o/.well-known/openid-configuration").json()

        self.assertEqual(document["issuer"], "https://sso.example.test/o")
        for key in ("authorization_endpoint", "token_endpoint", "userinfo_endpoint", "jwks_uri"):
            self.assertTrue(document[key].startswith("https://sso.example.test/o/"), key)

    def test_debug_with_a_public_host_raises_a_warning(self):
        from .checks import debug_on_public_host

        with self.settings(DEBUG=True, ALLOWED_HOSTS=["sso.szlg.info"]):
            warnings = debug_on_public_host(None)
        self.assertEqual([warning.id for warning in warnings], ["szlgplus.W001"])

        for debug, hosts in ((False, ["sso.szlg.info"]), (True, ["localhost", "127.0.0.1", "0.0.0.0"])):
            with self.settings(DEBUG=debug, ALLOWED_HOSTS=hosts):
                self.assertEqual(debug_on_public_host(None), [])


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class ConsentErrorPageTests(TestCase):
    """Invalid authorization requests must explain themselves instead of looking like a consent page."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(email="student@example.org", password="x-Pass-123456!")
        self.application = Application.objects.create(
            name="Igazoláskezelő",
            user=self.user,
            client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://ikapi.example/api/auth/sso/callback",
            algorithm=Application.RS256_ALGORITHM,
        )
        self.client.force_login(self.user)

    def _authorize(self, **overrides):
        params = {
            "response_type": "code",
            "client_id": self.application.client_id,
            "redirect_uri": "https://ikapi.example/api/auth/sso/callback",
            "scope": "openid profile",
            "state": "s",
            "nonce": "n",
            "code_challenge": "c" * 43,
            "code_challenge_method": "S256",
        }
        params.update(overrides)
        return self.client.get("/o/authorize/?" + urlencode(params))

    def test_mismatching_redirect_uri_is_explained_and_logged(self):
        wrong = "https://sso.example/api/auth/sso/callback"

        with self.assertLogs("szlg_plusz.oidc_urls", level="WARNING") as logs:
            response = self._authorize(redirect_uri=wrong)

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "nem egyezik az alkalmazás regisztrált URI", status_code=400)
        self.assertContains(response, "Mismatching redirect URI.", status_code=400)
        self.assertContains(response, wrong, status_code=400)
        self.assertNotContains(response, "Engedélyezés", status_code=400)
        self.assertNotContains(response, "Alapvető bejelentkezés", status_code=400)
        self.assertIn(wrong, logs.output[0])

    def test_unknown_client_is_explained(self):
        response = self._authorize(client_id="does-not-exist")

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Ismeretlen alkalmazás", status_code=400)
        self.assertNotContains(response, "Engedélyezés", status_code=400)

    def test_a_valid_request_still_shows_the_consent_page(self):
        response = self._authorize()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Engedélyezés")
        self.assertNotContains(response, "Hibakód")


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class AccountChooserTests(TestCase):
    PASSWORD = "chooser-password-123!x"

    def setUp(self):
        cache.clear()
        config = GlobalConfig.get_solo()
        config.promote_passkey = False
        config.save()
        self.first = CustomUser.objects.create_user(
            email="first@example.org",
            password=self.PASSWORD,
            first_name="Anna",
            last_name="Minta",
        )
        self.second = CustomUser.objects.create_user(
            email="second@example.org",
            password=self.PASSWORD,
            first_name="Béla",
            last_name="Példa",
        )

    def _password_login(self, email, **extra):
        return self.client.post(
            "/login/password/",
            {"email": email, "password": self.PASSWORD, **extra},
        )

    def test_signed_account_cookie_survives_logout_and_populates_chooser(self):
        self.assertRedirects(
            self._password_login(self.first.email), "/dashboard/", fetch_redirect_response=False
        )
        self.client.post("/logout/")

        self.assertIn("szlg_accounts", self.client.cookies)
        chooser = self.client.get("/login/")

        self.assertContains(chooser, "Fiókválasztó")
        self.assertContains(chooser, self.first.email)
        self.assertContains(chooser, "Minta Anna")
        self.assertNotContains(chooser, 'id="email"')

    def test_selected_account_skips_identifier_and_is_bound_to_cookie_identity(self):
        self._password_login(self.first.email)
        self.client.post("/logout/")
        selected = self.client.get(f"/login/?account={self.first.pk}")
        self.assertContains(selected, 'name="account_id"')
        self.assertNotContains(selected, 'id="email"')

        response = self.client.post(
            "/login/password/",
            {
                "account_id": self.first.pk,
                "email": self.second.email,
                "password": self.PASSWORD,
            },
        )

        self.assertRedirects(response, "/dashboard/", fetch_redirect_response=False)
        self.assertEqual(str(self.client.session["_auth_user_id"]), str(self.first.pk))

    def test_adding_an_account_keeps_recent_accounts_and_tampering_is_ignored(self):
        self._password_login(self.first.email)
        self.client.post("/logout/")
        self.client.get("/login/?add_account=1")
        self._password_login(self.second.email, add_account="1")
        self.client.post("/logout/")

        chooser = self.client.get("/login/")
        self.assertContains(chooser, self.first.email)
        self.assertContains(chooser, self.second.email)

        self.client.cookies["szlg_accounts"] = str(self.first.pk)
        tampered = self.client.get("/login/")
        self.assertNotContains(tampered, "Fiókválasztó")
        self.assertContains(tampered, 'id="email"')


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class DurableOAuthGrantTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="oauth-user@example.org", password="oauth-password-123!x"
        )
        self.application = Application.objects.create(
            name="Fiókportál",
            user=self.user,
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://client.example/callback",
            algorithm=Application.RS256_ALGORITHM,
        )
        self.authorization = {
            "response_type": "code",
            "client_id": self.application.client_id,
            "redirect_uri": "https://client.example/callback",
            "scope": "openid profile email",
            "state": "chooser-test-state",
            "nonce": "chooser-test-nonce",
            "code_challenge": "c" * 43,
            "code_challenge_method": "S256",
        }
        self.client.force_login(self.user)

    def _authorization_url(self, **overrides):
        params = {**self.authorization, **overrides}
        return "/o/authorize/?" + urlencode(params)

    def _approve_first_grant(self):
        consent = self.client.get(self._authorization_url())
        self.assertEqual(consent.status_code, 200)
        parser = HiddenInputParser()
        parser.feed(consent.content.decode())
        return self.client.post(parser.form_action, {**parser.values, "allow": "true"})

    def test_approved_grant_is_persistent_and_returns_to_confirmation_not_consent(self):
        approval = self._approve_first_grant()
        self.assertEqual(approval.status_code, 302)
        connection = UserAppConnection.objects.get(user=self.user, application=self.application)
        self.assertEqual(set(connection.scopes), {"openid", "profile", "email"})
        self.assertEqual(connection.interaction_mode, UserAppConnection.InteractionMode.CONFIRM)

        confirmation = self.client.get(self._authorization_url(state="second-state"))
        self.assertEqual(confirmation.status_code, 200)
        self.assertContains(confirmation, "A következő applikációba tervezel újra bejelentkezni")
        self.assertContains(confirmation, "Fiókportál")
        self.assertNotContains(confirmation, "Hozzáférés engedélyezése")

        parser = HiddenInputParser()
        parser.feed(confirmation.content.decode())
        resumed = self.client.post(
            parser.form_action,
            {**parser.values, "state": "second-state", "allow": "true"},
        )
        self.assertEqual(resumed.status_code, 302)
        self.assertIn("code", parse_qs(urlparse(resumed["Location"]).query), resumed["Location"])
        replay = self.client.post(
            parser.form_action,
            {**parser.values, "state": "second-state", "allow": "true"},
        )
        self.assertEqual(replay.status_code, 400)

    def test_automatic_mode_skips_confirmation_but_new_scopes_need_consent(self):
        UserAppConnection.objects.create(
            user=self.user,
            application=self.application,
            scopes=["openid", "profile", "email"],
            interaction_mode=UserAppConnection.InteractionMode.AUTOMATIC,
        )

        automatic = self.client.get(self._authorization_url())
        self.assertEqual(automatic.status_code, 302)
        self.assertIn("code", parse_qs(urlparse(automatic["Location"]).query))

        expanded = self.client.get(self._authorization_url(scope="openid profile groups"))
        self.assertEqual(expanded.status_code, 200)
        self.assertContains(expanded, "Hozzáférés engedélyezése")

    def test_confirmation_can_return_interaction_required_without_ui_for_prompt_none(self):
        UserAppConnection.objects.create(
            user=self.user,
            application=self.application,
            scopes=["openid", "profile", "email"],
            interaction_mode=UserAppConnection.InteractionMode.CONFIRM,
        )

        response = self.client.get(self._authorization_url(prompt="none"))

        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlparse(response["Location"]).query)
        self.assertEqual(query["error"], ["interaction_required"])
        self.assertEqual(query["state"], [self.authorization["state"]])

    def test_dashboard_can_change_and_revoke_a_durable_grant(self):
        connection = UserAppConnection.objects.create(
            user=self.user,
            application=self.application,
            scopes=["openid", "profile"],
        )

        updated = self.client.post(
            f"/grants/{self.application.pk}/interaction/",
            {"interaction_mode": UserAppConnection.InteractionMode.AUTOMATIC},
        )
        self.assertRedirects(updated, "/grants/", fetch_redirect_response=False)
        connection.refresh_from_db()
        self.assertEqual(
            connection.interaction_mode,
            UserAppConnection.InteractionMode.AUTOMATIC,
        )

        revoked = self.client.post(f"/grants/{self.application.pk}/revoke/")
        self.assertRedirects(revoked, "/grants/", fetch_redirect_response=False)
        self.assertFalse(
            UserAppConnection.objects.filter(
                user=self.user, application=self.application
            ).exists()
        )
