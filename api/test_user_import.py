import json
from datetime import date
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from oauth2_provider.models import Application

from .models import (
    CustomUser,
    GlobalConfig,
    SchoolClass,
    StudentProfile,
    Tagozat,
    TeacherProfile,
)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class UserImportTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_superuser(
            email="admin@example.org", password="admin-password-123!x"
        )
        config = GlobalConfig.get_solo()
        config.school_domain = "@example.org"
        config.save()
        self.client.force_login(self.admin)
        self.preview_url = reverse("user-import-preview")
        self.import_url = reverse("user-import-one")
        self.tagozat = Tagozat.objects.create(name="Nappali", slug="nappali")
        self.source_app = self._create_source_app("Régi napló")

    def _create_source_app(self, name):
        return Application.objects.create(
            name=name,
            user=self.admin,
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://legacy.example/callback",
            algorithm=Application.RS256_ALGORITHM,
        )

    def _post_json(self, url, payload):
        return self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def _preview(self, users, source_apps=None):
        source_apps = source_apps or [self.source_app]
        return self._post_json(
            self.preview_url,
            {"users": users, "source_app_ids": [app.pk for app in source_apps]},
        )

    def _import_one(self, user, source_apps=None):
        source_apps = source_apps or [self.source_app]
        return self._post_json(
            self.import_url,
            {"user": user, "source_app_ids": [app.pk for app in source_apps]},
        )

    def test_only_superusers_can_open_the_page_or_use_the_endpoints(self):
        self.client.logout()
        response = self.client.get(reverse("user-import"))
        self.assertEqual(response.status_code, 302)

        regular = CustomUser.objects.create_user(email="regular@example.org")
        self.client.force_login(regular)
        self.assertEqual(self.client.get(reverse("user-import")).status_code, 403)
        self.assertEqual(
            self._preview([{"email": "new@example.org"}]).status_code,
            403,
        )

        staff = CustomUser.objects.create_user(email="staff@example.org", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse("user-import")).status_code, 403)

        self.client.force_login(self.admin)
        page = self.client.get(reverse("user-import"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Felhasználói adatbázis importálása")
        self.assertContains(page, "2023F")
        self.assertContains(page, "nappali")
        self.assertContains(page, "Régi napló")
        self.assertContains(page, 'href="/admin/user-import/"')

    def test_preview_normalizes_records_and_reports_existing_accounts(self):
        CustomUser.objects.create_user(
            email="already@example.org", first_name="Régi", last_name="Fiók"
        )
        payload = [
            {
                "email": "NEW@example.org",
                "first_name": "Anna",
                "last_name": "Minta",
                "osztaly": "2023f",
                "tagozat": "Nappali",
            },
            {"email": "already@example.org", "first_name": "Másik"},
            {"email": "invalid"},
        ]

        response = self._preview(payload)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["counts"], {"new": 1, "existing": 1, "invalid": 1})
        self.assertEqual(body["rows"][0]["data"]["email"], "new@example.org")
        self.assertEqual(body["rows"][0]["data"]["kezdes_eve"], 2023)
        self.assertEqual(body["rows"][0]["data"]["szekcio"], "F")
        self.assertEqual(body["rows"][0]["data"]["tagozat"], "nappali")
        self.assertEqual(body["rows"][1]["status"], "existing")
        self.assertEqual(body["rows"][2]["status"], "invalid")
        self.assertFalse(CustomUser.objects.filter(email="new@example.org").exists())

    @patch("api.user_import_views._current_school_year", return_value=2026)
    def test_current_grade_class_is_converted_to_a_cohort(self, _current_school_year):
        response = self._preview(
            [{"email": "student@example.org", "osztaly": "10. F"}]
        )

        self.assertEqual(response.status_code, 200)
        record = response.json()["rows"][0]["data"]
        self.assertEqual(record["kezdes_eve"], 2024)
        self.assertEqual(record["szekcio"], "F")

    def test_teacher_is_not_assigned_a_class_from_student_like_email(self):
        existing_teacher = CustomUser.objects.create_user(
            email="old.teacher.23a@example.org"
        )
        TeacherProfile.objects.create(user=existing_teacher, employee_number="T-42")
        self.assertFalse(existing_teacher.is_student)
        self.assertEqual(existing_teacher.account_type, "Tanár/iskolai alkalmazott")

        response = self._preview(
            [
                {"email": "teacher.23a@example.org", "employee_number": "T-43"},
                {"email": existing_teacher.email},
                {"email": "explicit.teacher.23a@example.org", "is_student": False},
            ]
        )

        self.assertEqual(response.status_code, 200)
        for row in response.json()["rows"]:
            with self.subTest(email=row["email"]):
                self.assertFalse(row["class_label"])
                self.assertFalse(row["class_inferred"])
                self.assertFalse(row["is_student"])
                self.assertFalse(row["needs_tagozat"])

        existing_teacher_row = response.json()["rows"][1]
        updated = self._import_one(existing_teacher_row["data"])
        self.assertEqual(updated.status_code, 200, updated.content)
        self.assertFalse(StudentProfile.objects.filter(user=existing_teacher).exists())

        imported = self._import_one(
            {"email": "teacher.23a@example.org", "employee_number": "T-43"}
        )
        self.assertEqual(imported.status_code, 200, imported.content)
        teacher = CustomUser.objects.get(email="teacher.23a@example.org")
        self.assertTrue(TeacherProfile.objects.filter(user=teacher).exists())
        self.assertFalse(StudentProfile.objects.filter(user=teacher).exists())
        self.assertFalse(teacher.is_student)

        explicit_teacher_row = response.json()["rows"][2]
        explicit_teacher = self._import_one(explicit_teacher_row["data"])
        self.assertEqual(explicit_teacher.status_code, 200, explicit_teacher.content)
        account = CustomUser.objects.get(email="explicit.teacher.23a@example.org")
        self.assertTrue(TeacherProfile.objects.filter(user=account).exists())
        self.assertFalse(StudentProfile.objects.filter(user=account).exists())
        self.assertFalse(account.is_student)

    def test_class_is_inferred_from_student_email_and_missing_tagozat_is_flagged(self):
        response = self._preview([{"email": "anna.minta.23f@example.org"}])

        self.assertEqual(response.status_code, 200)
        row = response.json()["rows"][0]
        self.assertEqual(row["data"]["kezdes_eve"], 2023)
        self.assertEqual(row["data"]["szekcio"], "F")
        self.assertTrue(row["class_inferred"])
        self.assertTrue(row["needs_tagozat"])

        row["data"]["tagozat"] = self.tagozat.slug
        imported = self._import_one(row["data"])
        self.assertEqual(imported.status_code, 200, imported.content)
        profile = StudentProfile.objects.get(user__email="anna.minta.23f@example.org")
        self.assertEqual((profile.kezdes_eve, profile.szekcio), (2023, "F"))
        self.assertEqual(profile.tagozat, self.tagozat)

    def test_import_sources_are_saved_and_accumulated_without_duplicates(self):
        other_app = self._create_source_app("Másik alkalmazás")
        first = self._import_one({"email": "source@example.org"})
        self.assertEqual(first.status_code, 200, first.content)

        second = self._import_one(
            {"email": "source@example.org"}, source_apps=[self.source_app, other_app]
        )
        self.assertEqual(second.status_code, 200, second.content)
        user = CustomUser.objects.get(email="source@example.org")
        self.assertEqual(
            [source["client_id"] for source in user.import_sources],
            [self.source_app.client_id, other_app.client_id],
        )
        self.assertEqual(second.json()["sources_added"], ["Másik alkalmazás"])

    def test_unrecognized_legacy_tagozat_can_be_replaced_in_bulk_preview(self):
        response = self._preview(
            [{"email": "student@example.org", "tagozat": "Régi esti"}]
        )

        self.assertEqual(response.status_code, 200)
        row = response.json()["rows"][0]
        self.assertEqual(row["status"], "new")
        self.assertTrue(row["needs_tagozat"])
        self.assertTrue(row["warnings"])
        self.assertNotIn("tagozat", row["data"])

        row["data"]["tagozat"] = self.tagozat.slug
        imported = self._import_one(row["data"])
        self.assertEqual(imported.status_code, 200, imported.content)
        self.assertEqual(
            StudentProfile.objects.get(user__email="student@example.org").tagozat,
            self.tagozat,
        )

    def test_student_marker_creates_profile_even_when_optional_fields_are_blank(self):
        response = self._import_one(
            {"email": "external-student@example.org", "is_student": True}
        )

        self.assertEqual(response.status_code, 200, response.content)
        profile = StudentProfile.objects.get(user__email="external-student@example.org")
        self.assertIsNone(profile.kezdes_eve)
        self.assertEqual(profile.szekcio, "")
        self.assertIsNone(profile.tagozat_id)
        self.assertEqual(profile.om_id, "")

    def test_import_creates_user_and_student_teacher_profiles(self):
        record = {
            "email": "anna@example.org",
            "last_name": "Minta",
            "first_name": "Anna",
            "phone": "+36 30 123 4567",
            "date_of_birth": "2008-03-21",
            "osztaly": "2023F",
            "om_id": "12345678901",
            "tagozat": "nappali",
            "employee_number": "M-1042",
        }

        response = self._import_one(record)

        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()
        self.assertEqual(result["status"], "created")
        self.assertIn("Vezetéknév", result["added"])
        self.assertIn("OM azonosító", result["added"])
        user = CustomUser.objects.get(email="anna@example.org")
        self.assertTrue(user.is_active)
        self.assertFalse(user.email_verified)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(
            user.import_sources,
            [{
                "application_id": self.source_app.pk,
                "client_id": self.source_app.client_id,
                "name": self.source_app.name,
            }],
        )
        self.assertEqual(user.date_of_birth, date(2008, 3, 21))
        self.assertEqual(user.phone, "+36 30 123 4567")

        student = StudentProfile.objects.get(user=user)
        self.assertEqual(student.kezdes_eve, 2023)
        self.assertEqual(student.szekcio, "F")
        self.assertEqual(student.om_id, "12345678901")
        self.assertEqual(student.tagozat, self.tagozat)
        self.assertTrue(
            SchoolClass.objects.filter(start_year=2023, section="F").exists()
        )
        self.assertEqual(TeacherProfile.objects.get(user=user).employee_number, "M-1042")

    def test_existing_account_is_only_enriched_and_import_is_idempotent(self):
        existing = CustomUser.objects.create_user(
            email="existing@example.org",
            password="keep-this-password",
            last_name="Meglévő",
            is_staff=True,
            email_verified=True,
        )
        student = StudentProfile.objects.create(
            user=existing,
            om_id="régi-om",
            kezdes_eve=2022,
            szekcio="F",
        )
        record = {
            "email": "EXISTING@example.org",
            "last_name": "Ne írja felül",
            "first_name": "Anna",
            "phone": "+36 20 111 2222",
            "osztaly": "2023F",
            "om_id": "új-om",
        }

        first = self._import_one(record)
        self.assertEqual(first.status_code, 200, first.content)
        result = first.json()
        self.assertEqual(result["status"], "updated")
        self.assertIn("Keresztnév", result["added"])
        self.assertIn("Vezetéknév", result["preserved"])
        self.assertTrue(result["warnings"])

        existing.refresh_from_db()
        student.refresh_from_db()
        self.assertEqual(existing.last_name, "Meglévő")
        self.assertEqual(existing.first_name, "Anna")
        self.assertEqual(existing.phone, "+36 20 111 2222")
        self.assertTrue(existing.is_staff)
        self.assertTrue(existing.email_verified)
        self.assertTrue(existing.check_password("keep-this-password"))
        self.assertEqual(student.om_id, "régi-om")
        self.assertEqual((student.kezdes_eve, student.szekcio), (2022, "F"))

        second = self._import_one(record)
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(second.json()["status"], "unchanged")

    def test_duplicate_emails_are_excluded_from_preview(self):
        response = self._preview(
            [
                {"email": "same@example.org", "first_name": "Egyik"},
                {"email": "SAME@example.org", "first_name": "Másik"},
            ],
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["counts"]["invalid"], 2)
        self.assertTrue(all(row["data"] is None for row in response.json()["rows"]))

    def test_invalid_or_privileged_fields_are_rejected_without_writes(self):
        for record in (
            {"email": "bad-date@example.org", "date_of_birth": "2008-02-31"},
            {"email": "unknown-group@example.org", "tagozat": "nincs-ilyen"},
            {"email": "privileged@example.org", "is_superuser": True},
        ):
            with self.subTest(record=record):
                response = self._import_one(record)
                self.assertEqual(response.status_code, 400)
        self.assertEqual(CustomUser.objects.filter(email__in=[
            "bad-date@example.org",
            "unknown-group@example.org",
            "privileged@example.org",
        ]).count(), 0)

    def test_preview_accepts_users_wrapper_and_enforces_request_shape(self):
        wrapped = self._post_json(
            self.preview_url,
            {"users": [{"email": "wrapped@example.org"}], "source_app_ids": [self.source_app.pk]},
        )
        self.assertEqual(wrapped.status_code, 200)
        malformed = self._post_json(
            self.preview_url,
            {
                "users": [],
                "source_app_ids": [self.source_app.pk],
                "source": "legacy",
            },
        )
        self.assertEqual(malformed.status_code, 400)
        missing_source = self._post_json(
            self.preview_url,
            {"users": [{"email": "no-source@example.org"}], "source_app_ids": []},
        )
        self.assertEqual(missing_source.status_code, 400)
