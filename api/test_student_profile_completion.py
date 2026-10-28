import json
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from .models import CustomUser, GlobalConfig, SchoolClass, StudentProfile, Tagozat


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class StudentProfileCompletionTests(TestCase):
    PASSWORD = "student-password-123!x"

    def setUp(self):
        config = GlobalConfig.get_solo()
        config.school_domain = "@example.org"
        config.promote_passkey = False
        config.save()
        self.user = CustomUser.objects.create_user(
            email="anna.minta.23a@example.org",
            password=self.PASSWORD,
        )
        self.tagozat = Tagozat.objects.create(name="Nappali", slug="nappali")
        self.url = reverse("student-profile-completion")

    def test_password_login_redirects_students_to_skippable_completion_page(self):
        response = self.client.post(
            "/login/password/",
            {
                "email": self.user.email,
                "password": self.PASSWORD,
                "next": "/apps/",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{self.url}?next=%2Fapps%2F")
        page = self.client.get(response["Location"])
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "A diákprofilod hiányos")
        self.assertContains(page, "Tagozat")
        self.assertContains(page, "OM azonosító")
        self.assertContains(page, "/static/img/om-id.gif")
        self.assertContains(page, "Most kihagyom")

    def test_passkey_login_also_redirects_to_profile_completion(self):
        with patch("api.web_views.verify_authentication", return_value=self.user):
            response = self.client.post(
                "/login/passkey/verify/",
                data=json.dumps(
                    {
                        "challenge_id": "test-challenge",
                        "credential": {},
                        "next": "/apps/",
                    }
                ),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["redirect"],
            f"{self.url}?next=%2Fapps%2F",
        )

    def test_saving_missing_data_preserves_existing_values_and_infers_class(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            {
                "next": "/dashboard/",
                "action": "save",
                "tagozat": self.tagozat.slug,
                "om_id": "7000012345",
            },
        )

        self.assertRedirects(response, "/dashboard/", fetch_redirect_response=False)
        profile = StudentProfile.objects.get(user=self.user)
        self.assertEqual(profile.tagozat, self.tagozat)
        self.assertEqual(profile.om_id, "7000012345")
        self.assertEqual((profile.kezdes_eve, profile.szekcio), (2023, "A"))
        self.assertTrue(SchoolClass.objects.filter(start_year=2023, section="A").exists())

        # A second POST cannot replace a value that is already populated.
        self.client.post(
            self.url,
            {
                "next": "/dashboard/",
                "action": "save",
                "tagozat": "másik",
                "om_id": "másik-azonosító",
            },
        )
        profile.refresh_from_db()
        self.assertEqual(profile.tagozat, self.tagozat)
        self.assertEqual(profile.om_id, "7000012345")

    def test_skip_suppresses_prompt_for_session_but_next_login_asks_again(self):
        self.client.force_login(self.user)
        skipped = self.client.post(
            self.url,
            {"next": "/dashboard/", "action": "skip"},
        )
        self.assertRedirects(skipped, "/dashboard/", fetch_redirect_response=False)
        self.assertEqual(
            self.client.session["student_profile_prompt_dismissed_user"],
            str(self.user.pk),
        )
        self.assertEqual(
            self.client.get("/login/?next=/apps/")["Location"],
            "/apps/",
        )

        self.client.post("/logout/")
        login = self.client.post(
            "/login/password/",
            {"email": self.user.email, "password": self.PASSWORD},
        )
        self.assertEqual(login["Location"], f"{self.url}?next=%2Fdashboard%2F")

    def test_prompt_only_shows_fields_that_are_missing_and_is_not_shown_for_nonstudents(self):
        StudentProfile.objects.create(user=self.user, om_id="7000012345")
        self.client.force_login(self.user)

        page = self.client.get(self.url)

        self.assertContains(page, "Tagozat")
        self.assertNotContains(page, 'name="om_id"')

        regular = CustomUser.objects.create_user(email="regular@example.org")
        self.client.force_login(regular)
        response = self.client.get(self.url)
        self.assertRedirects(response, "/dashboard/", fetch_redirect_response=False)
