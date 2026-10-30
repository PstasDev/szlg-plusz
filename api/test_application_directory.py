from django.test import TestCase
from django.urls import reverse
from oauth2_provider.models import Application

from .models import ApplicationProfile, CustomUser


class SupportedApplicationsDirectoryTests(TestCase):
    def setUp(self):
        self.owner = CustomUser.objects.create_user(
            email="developer@example.org",
            password="test-password-123!x",
            first_name="Minta",
            last_name="Fejlesztő",
        )

    def create_application(
        self,
        name,
        *,
        developer="Minta fejlesztő",
        short_description="Leírás az alkalmazáshoz.",
        launch_url="https://app.example.org/",
        verified=False,
        grant_type=Application.GRANT_AUTHORIZATION_CODE,
        with_profile=True,
    ):
        application = Application.objects.create(
            name=name,
            user=self.owner,
            client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=grant_type,
            redirect_uris="https://private.example.org/oauth/callback/",
            algorithm=Application.RS256_ALGORITHM,
        )
        if with_profile:
            ApplicationProfile.objects.create(
                application=application,
                developer=developer,
                short_description=short_description,
                launch_url=launch_url,
                verified=verified,
            )
        return application

    def test_public_directory_lists_sso_apps_and_safe_public_metadata(self):
        self.create_application(
            "Igazoláskezelő",
            developer="SZLG",
            short_description="Iskolai igazolások kezelése.",
            verified=True,
        )
        self.create_application(
            "Stúdió",
            developer="Minta fejlesztő",
            launch_url="",
            verified=False,
        )
        self.create_application("Kliens profil nélkül", with_profile=False)
        self.create_application(
            "Gépi kliens",
            grant_type=Application.GRANT_CLIENT_CREDENTIALS,
        )

        response = self.client.get(reverse("supported-applications"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Igazoláskezelő")
        self.assertContains(response, "Iskolai igazolások kezelése.")
        self.assertContains(response, "Ellenőrzött")
        self.assertContains(response, "Nem ellenőrzött")
        self.assertContains(response, "Stúdió")
        self.assertContains(response, 'href="https://app.example.org/"')
        self.assertContains(response, "Indítási oldal nincs megadva")
        self.assertContains(response, "Kliens profil nélkül")
        self.assertContains(response, "Fejlesztő nincs megadva")
        self.assertNotContains(response, "Gépi kliens")
        self.assertNotContains(response, "private.example.org")

    def test_search_matches_application_name_developer_and_description(self):
        self.create_application(
            "Igazoláskezelő",
            developer="SZLG",
            short_description="Digitális ügyintézés",
        )
        self.create_application(
            "Stúdió",
            developer="Másik csapat",
            short_description="Hang- és videómunka",
        )
        self.create_application("Kiegészítő kliens", with_profile=False)

        by_name = self.client.get(
            reverse("supported-applications"), {"q": "igazolás"}
        )
        self.assertContains(by_name, "Igazoláskezelő")
        self.assertNotContains(by_name, "Stúdió")

        by_developer = self.client.get(
            reverse("supported-applications"), {"q": "másik csapat"}
        )
        self.assertContains(by_developer, "Stúdió")
        self.assertNotContains(by_developer, "Igazoláskezelő")

        by_description = self.client.get(
            reverse("supported-applications"), {"q": "videómunka"}
        )
        self.assertContains(by_description, "Stúdió")
        self.assertNotContains(by_description, "Igazoláskezelő")

        without_profile = self.client.get(
            reverse("supported-applications"), {"q": "Kiegészítő kliens"}
        )
        self.assertContains(without_profile, "Kiegészítő kliens")

    def test_verified_filter_hides_unverified_apps(self):
        self.create_application("Ellenőrzött app", verified=True)
        self.create_application("Nem ellenőrzött app", verified=False)

        response = self.client.get(reverse("supported-applications"), {"verified": "1"})

        self.assertContains(response, "Ellenőrzött app")
        self.assertNotContains(response, "Nem ellenőrzött app")

    def test_empty_search_has_a_recoverable_empty_state(self):
        self.create_application("Stúdió")

        response = self.client.get(
            reverse("supported-applications"),
            {"q": "nincs ilyen alkalmazás"},
        )

        self.assertContains(response, "Nincs ilyen alkalmazás")
        self.assertContains(response, "Összes alkalmazás")
