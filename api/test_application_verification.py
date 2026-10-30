from importlib import import_module
from types import SimpleNamespace
from urllib.parse import urlencode

from django.apps import apps
from django.core import mail
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from oauth2_provider.models import Application

from .models import (
    ApplicationProfile,
    ApplicationVerificationRequest,
    CustomUser,
    GlobalConfig,
    UserAppConnection,
)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class ApplicationVerificationTests(TestCase):
    def setUp(self):
        config = GlobalConfig.get_solo()
        config.school_domain = "@example.org"
        config.terms_of_service_url = "https://sso.example.org/aszf/"
        config.save()

        self.owner = CustomUser.objects.create_user(
            email="developer@example.org",
            password="test-password-123!x",
            first_name="Minta",
            last_name="Fejlesztő",
        )
        self.reviewer = CustomUser.objects.create_superuser(
            email="reviewer@example.org",
            password="reviewer-password-123!x",
        )
        self.application = self.create_application(self.owner)
        self.client.force_login(self.owner)

    def create_application(self, owner, *, name="Ellenőrzésre váró app"):
        application = Application.objects.create(
            name=name,
            user=owner,
            client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://app.example.org/oauth/callback/",
            algorithm=Application.RS256_ALGORITHM,
        )
        ApplicationProfile.objects.create(
            application=application,
            developer="Minta Fejlesztő",
            short_description="Iskolai alkalmazás.",
            launch_url="https://app.example.org/",
        )
        return application

    def complete_metadata(self, application=None, **overrides):
        application = application or self.application
        values = {
            "name": application.name,
            "short_description": application.profile.short_description,
            "developer": application.profile.developer,
            "launch_url": application.profile.launch_url,
            "privacy_contact_name": "Adatvédelmi csoport",
            "privacy_contact_email": "privacy@app.example.org",
            "privacy_policy_source": "own",
            "privacy_policy_url": "https://app.example.org/privacy/",
            "terms_of_service_source": "own",
            "terms_of_service_url": "https://app.example.org/terms/",
            "client_type": application.client_type,
            "redirect_uris": application.redirect_uris,
        }
        values.update(overrides)
        return self.client.post(
            reverse("application-edit", args=[application.pk]), values
        )

    def submit_verification(self, application=None):
        application = application or self.application
        return self.client.post(
            reverse("application-verification-request", args=[application.pk]),
            {"developer_note": "Kérem az alkalmazás ellenőrzését."},
        )

    def test_incomplete_application_cannot_request_verification(self):
        response = self.submit_verification()

        self.assertRedirects(
            response,
            reverse("application-edit", args=[self.application.pk]),
            fetch_redirect_response=False,
        )
        self.assertFalse(
            ApplicationVerificationRequest.objects.filter(
                application=self.application
            ).exists()
        )
        self.application.profile.refresh_from_db()
        self.assertFalse(self.application.profile.verified)

    def test_group_selector_renders_searchable_checkbox_options(self):
        response = self.client.get(
            reverse("application-edit", args=[self.application.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-group-selector-search')
        self.assertContains(response, 'data-group-selector-option')
        self.assertContains(response, 'type="checkbox"')
        self.assertContains(response, "Csoportok keresése")

    def test_group_selector_saves_multiple_group_requirements(self):
        self.complete_metadata(required_group_keys=["smart-student", "smart-teacher"])

        self.application.profile.refresh_from_db()
        self.assertEqual(
            self.application.profile.required_group_keys,
            ["smart-student", "smart-teacher"],
        )

    def test_developer_can_submit_and_admin_can_approve_request(self):
        self.complete_metadata()
        self.application.refresh_from_db()

        response = self.submit_verification()

        self.assertRedirects(
            response,
            reverse("application-detail", args=[self.application.pk]),
            fetch_redirect_response=False,
        )
        verification_request = ApplicationVerificationRequest.objects.get(
            application=self.application
        )
        self.assertEqual(
            verification_request.status,
            ApplicationVerificationRequest.Status.PENDING,
        )
        self.assertEqual(verification_request.submitted_by, self.owner)
        self.assertFalse(self.application.profile.verified)
        self.assertEqual(len(mail.outbox), 2)

        self.client.force_login(self.reviewer)
        queue = self.client.get(reverse("application-review-list"))
        self.assertContains(queue, self.application.name)
        detail = self.client.get(
            reverse("application-review-detail", args=[verification_request.pk])
        )
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Adatvédelmi kapcsolattartó")

        response = self.client.post(
            reverse("application-review-detail", args=[verification_request.pk]),
            {"action": "approve", "reviewer_note": "Ellenőrizve."},
        )

        self.assertRedirects(
            response,
            reverse("application-review-list"),
            fetch_redirect_response=False,
        )
        self.application.profile.refresh_from_db()
        verification_request.refresh_from_db()
        self.assertTrue(self.application.profile.verified)
        self.assertEqual(
            verification_request.status,
            ApplicationVerificationRequest.Status.APPROVED,
        )
        self.assertEqual(verification_request.reviewed_by, self.reviewer)
        catalog = self.client.get(reverse("supported-applications"))
        self.assertContains(catalog, "Utoljára ellenőrizve")

    def test_staff_owner_does_not_auto_verify_new_app(self):
        self.owner.is_staff = True
        self.owner.save(update_fields=["is_staff"])
        response = self.client.post(
            reverse("application-new"),
            {
                "name": "Staff által létrehozott app",
                "short_description": "Leírás",
                "developer": "Iskolai fejlesztő",
                "client_type": Application.CLIENT_CONFIDENTIAL,
                "redirect_uris": "https://app.example.org/callback/",
            },
        )

        self.assertEqual(response.status_code, 200)
        application = Application.objects.get(name="Staff által létrehozott app")
        self.assertFalse(application.profile.verified)

    def test_owner_cannot_approve_their_own_application(self):
        self.complete_metadata()
        self.submit_verification()
        verification_request = ApplicationVerificationRequest.objects.get(
            application=self.application
        )
        self.owner.is_staff = True
        self.owner.save(update_fields=["is_staff"])

        response = self.client.post(
            reverse("application-review-detail", args=[verification_request.pk]),
            {"action": "approve", "reviewer_note": ""},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Saját alkalmazásod ellenőrzési kérelmét")
        self.application.profile.refresh_from_db()
        verification_request.refresh_from_db()
        self.assertFalse(self.application.profile.verified)
        self.assertEqual(
            verification_request.status,
            ApplicationVerificationRequest.Status.PENDING,
        )

    def test_changing_application_details_supersedes_pending_review(self):
        self.complete_metadata()
        self.submit_verification()
        verification_request = ApplicationVerificationRequest.objects.get(
            application=self.application
        )

        response = self.complete_metadata(short_description="Új leírás")

        self.assertRedirects(
            response,
            reverse("application-detail", args=[self.application.pk]),
            fetch_redirect_response=False,
        )
        verification_request.refresh_from_db()
        self.assertEqual(
            verification_request.status,
            ApplicationVerificationRequest.Status.SUPERSEDED,
        )
        self.application.profile.refresh_from_db()
        self.assertFalse(self.application.profile.verified)

    def test_catalog_and_user_grants_show_privacy_contact_and_documents(self):
        self.complete_metadata()
        self.application.refresh_from_db()
        UserAppConnection.objects.create(
            user=self.owner,
            application=self.application,
            scopes=["openid", "email"],
        )

        catalog = self.client.get(reverse("supported-applications"))
        grants = self.client.get(reverse("grants"))

        for response in (catalog, grants):
            self.assertContains(response, "privacy@app.example.org")
            self.assertContains(response, "https://app.example.org/privacy/")
            self.assertContains(response, "https://app.example.org/terms/")

    def test_szlg_terms_declaration_requires_configured_central_url(self):
        config = GlobalConfig.get_solo()
        config.terms_of_service_url = ""
        config.save(update_fields=["terms_of_service_url"])

        response = self.complete_metadata(
            terms_of_service_source="szlg",
            terms_of_service_url="",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ÁSZF URL-je még nincs beállítva")
        self.assertEqual(
            ApplicationVerificationRequest.objects.filter(
                application=self.application
            ).count(),
            0,
        )

    def test_application_can_declare_szlg_documents_when_configured(self):
        self.complete_metadata(
            privacy_policy_source="szlg",
            privacy_policy_url="",
            terms_of_service_source="szlg",
            terms_of_service_url="",
        )
        self.application.refresh_from_db()

        self.assertTrue(self.application.profile.uses_szlg_privacy_policy)
        self.assertTrue(self.application.profile.uses_szlg_terms_of_service)
        self.assertRedirects(
            self.submit_verification(),
            reverse("application-detail", args=[self.application.pk]),
            fetch_redirect_response=False,
        )
        catalog = self.client.get(reverse("supported-applications"))
        self.assertContains(catalog, "/adatvedelem/")
        self.assertContains(catalog, "https://sso.example.org/aszf/")

    def test_legacy_verified_apps_are_demoted_and_queued_for_review(self):
        self.application.profile.verified = True
        self.application.profile.save(update_fields=["verified"])
        migration = import_module(
            "api.migrations.0021_application_verification_workflow"
        )

        migration.queue_legacy_verified_apps(
            apps, SimpleNamespace(connection=connection)
        )

        self.application.profile.refresh_from_db()
        verification_request = ApplicationVerificationRequest.objects.get(
            application=self.application
        )
        self.assertFalse(self.application.profile.verified)
        self.assertEqual(
            verification_request.status,
            ApplicationVerificationRequest.Status.LEGACY_REVIEW,
        )
        self.assertIsNone(verification_request.submitted_by)

        migration.restore_legacy_verified_apps(
            apps, SimpleNamespace(connection=connection)
        )
        self.application.profile.refresh_from_db()
        self.assertTrue(self.application.profile.verified)
        self.assertFalse(
            ApplicationVerificationRequest.objects.filter(
                application=self.application
            ).exists()
        )

    def test_consent_page_shows_application_legal_information(self):
        self.complete_metadata()
        self.application.refresh_from_db()
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.application.client_id,
                "redirect_uri": "https://app.example.org/oauth/callback/",
                "scope": "openid email",
                "state": "state-value",
                "code_challenge": "c" * 43,
                "code_challenge_method": "S256",
            }
        )

        response = self.client.get(f"/o/authorize/?{query}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Az Engedélyezés gombra kattintva elfogadod")
        self.assertContains(response, "az alkalmazás adatkezelési tájékoztatóját")
        self.assertContains(response, "az alkalmazás ÁSZF-jét")
        self.assertContains(response, "https://app.example.org/privacy/")
        self.assertContains(response, "https://app.example.org/terms/")
        self.assertNotContains(response, "Adatvédelem és kapcsolattartás")
        self.assertNotContains(response, "privacy@app.example.org")
