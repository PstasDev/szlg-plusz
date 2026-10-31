import re

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from django.urls import reverse

from .models import (
    AccountReviewStatus,
    CustomUser,
    GlobalConfig,
    ManualReviewRequest,
    SchoolAccountOTP,
    StudentProfile,
    TeacherProfile,
)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class SchoolAccountFlowTests(TestCase):
    PASSWORD = "Maple-OTP-Password-69!"

    def setUp(self):
        cache.clear()
        config = GlobalConfig.get_solo()
        config.school_domain = "@example.org"
        config.promote_passkey = False
        config.save()
        config.administrator_contacts.clear()
        self.admin = CustomUser.objects.create_user(
            email="admin@example.org",
            password="Admin-Password-93!",
            first_name="Admin",
            last_name="Review",
            is_staff=True,
        )
        config.administrator_contacts.add(self.admin)

    def _registration_data(self, **overrides):
        data = {
            "first_name": "Anna",
            "last_name": "Minta",
            "phone": "+36 30 123 4567",
            "date_of_birth": "2008-03-21",
            "om_id": "7000012345",
            "password1": self.PASSWORD,
            "password2": self.PASSWORD,
            "privacy_consent": "on",
        }
        data.update(overrides)
        return data

    def _submit_student_registration(self, email="anna.minta.23a@example.org"):
        start = self.client.post(reverse("school-account-setup"), {"email": email})
        self.assertRedirects(
            start,
            reverse("school-account-register"),
            fetch_redirect_response=False,
        )
        return self.client.post(
            reverse("school-account-register"), self._registration_data()
        )

    def _pending_review(self, email="candidate@example.org", applicant_type=None):
        user = CustomUser.objects.create_user(
            email=email,
            password=self.PASSWORD,
            first_name="Jelölt",
            last_name="Minta",
            is_active=False,
            email_verified=False,
            account_review_status=AccountReviewStatus.PENDING,
            privacy_consent_at=timezone.now(),
        )
        applicant_type = applicant_type or ManualReviewRequest.ApplicantType.SCHOOL_EMPLOYEE
        review = ManualReviewRequest.objects.create(
            user=user,
            applicant_type=applicant_type,
            position="Iskolai munkatárs",
        )
        return user, review

    def _review_data(self, action, **overrides):
        data = {
            "first_name": "Módosított",
            "last_name": "Jelölt",
            "phone": "+36 30 123 4567",
            "date_of_birth": "",
            "applicant_type": ManualReviewRequest.ApplicantType.SCHOOL_EMPLOYEE,
            "position": "Iskolai munkatárs",
            "employee_number": "A-123",
            "om_id": "",
            "tagozat": "",
            "kezdes_eve": "",
            "szekcio": "",
            "reviewer_note": "Ellenőrizve.",
            "action": action,
        }
        data.update(overrides)
        return data

    def test_login_offers_school_account_setup(self):
        response = self.client.get(reverse("login"))

        self.assertContains(response, "Iskolai fiókom van és még nincs jelszavam")
        self.assertContains(response, reverse("school-account-setup"))

    def test_existing_account_receives_otp_and_can_set_a_password(self):
        user = CustomUser.objects.create_user(
            email="anna.minta.23a@example.org",
            first_name="Anna",
            last_name="Minta",
        )
        self.assertFalse(user.has_usable_password())

        start = self.client.post(
            reverse("school-account-setup"), {"email": user.email}
        )

        self.assertRedirects(
            start,
            reverse("school-account-otp"),
            fetch_redirect_response=False,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [user.email])
        html_body, mime_type = mail.outbox[0].alternatives[0]
        self.assertEqual(mime_type, "text/html")
        self.assertIn("E-mail-cím ellenőrzése", html_body)
        self.assertIn("#102a2b", html_body)
        code = re.search(r"(?<!\d)\d{6}(?!\d)", mail.outbox[0].body).group(0)
        challenge = SchoolAccountOTP.objects.get(user=user)
        self.assertNotEqual(challenge.code_hash, code)

        verified = self.client.post(reverse("school-account-otp"), {"code": code})
        self.assertRedirects(
            verified,
            reverse("school-account-password"),
            fetch_redirect_response=False,
        )
        password = self.client.post(
            reverse("school-account-password"),
            {"new_password1": self.PASSWORD, "new_password2": self.PASSWORD},
        )

        self.assertRedirects(
            password,
            reverse("password-reset-complete"),
            fetch_redirect_response=False,
        )
        user.refresh_from_db()
        self.assertTrue(user.check_password(self.PASSWORD))
        self.assertFalse(SchoolAccountOTP.objects.filter(user=user).exists())

        login = self.client.post(
            reverse("password-login"),
            {"email": user.email, "password": self.PASSWORD},
        )
        self.assertEqual(login.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)

    def test_an_unknown_student_account_is_flagged_and_cannot_log_in_until_approved(self):
        response = self._submit_student_registration()

        self.assertRedirects(
            response,
            reverse("school-account-submitted"),
            fetch_redirect_response=False,
        )
        self.assertContains(self.client.get(response["Location"]), "Felülvizsgálatra vár")
        user = CustomUser.objects.get(email="anna.minta.23a@example.org")
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertFalse(user.email_verified)
        self.assertEqual(user.account_review_status, AccountReviewStatus.PENDING)
        self.assertTrue(user.check_password(self.PASSWORD))
        self.assertEqual(user.privacy_consent_at is not None, True)
        self.assertEqual(user.manual_review_request.applicant_type, "student")
        profile = StudentProfile.objects.get(user=user)
        self.assertEqual(profile.om_id, "7000012345")
        self.assertEqual((profile.kezdes_eve, profile.szekcio), (2023, "A"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.admin.email])
        self.assertIn(reverse("manual-review-list"), mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].alternatives[0][1], "text/html")
        self.assertIn(
            "Új fiók vár manuális felülvizsgálatra",
            mail.outbox[0].alternatives[0][0],
        )
        self.assertContains(self.client.get(response["Location"]), self.admin.email)

        denied = self.client.post(
            reverse("password-login"),
            {"email": user.email, "password": self.PASSWORD},
        )
        self.assertEqual(denied.status_code, 401)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_unknown_nonstudent_must_supply_a_school_role_and_work_details(self):
        start = self.client.post(
            reverse("school-account-setup"), {"email": "tanar@example.org"}
        )
        self.assertRedirects(
            start,
            reverse("school-account-register"),
            fetch_redirect_response=False,
        )
        registration_page = self.client.get(reverse("school-account-register"))
        self.assertContains(registration_page, "Tanári vagy munkatársi fiók regisztrációja")
        self.assertContains(registration_page, 'name="applicant_type"')
        self.assertContains(registration_page, 'name="position"')

        data = self._registration_data(
            applicant_type=ManualReviewRequest.ApplicantType.TEACHER,
            position="Matematikatanár",
            employee_number="T-42",
        )
        response = self.client.post(reverse("school-account-register"), data)

        self.assertRedirects(
            response,
            reverse("school-account-submitted"),
            fetch_redirect_response=False,
        )
        user = CustomUser.objects.get(email="tanar@example.org")
        self.assertEqual(
            user.manual_review_request.applicant_type,
            ManualReviewRequest.ApplicantType.TEACHER,
        )
        self.assertEqual(user.manual_review_request.position, "Matematikatanár")
        self.assertEqual(TeacherProfile.objects.get(user=user).employee_number, "T-42")

    def test_pending_or_rejected_accounts_do_not_get_an_otp(self):
        pending, _ = self._pending_review(email="pending@example.org")
        response = self.client.post(
            reverse("school-account-setup"), {"email": pending.email}
        )
        self.assertContains(response, "adminisztratív felülvizsgálat alatt áll")
        self.assertContains(response, self.admin.email)
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(SchoolAccountOTP.objects.filter(user=pending).exists())

        pending.account_review_status = AccountReviewStatus.REJECTED
        pending.save(update_fields=["account_review_status"])
        response = self.client.post(
            reverse("school-account-setup"), {"email": pending.email}
        )
        self.assertContains(response, "nem hagyták jóvá")
        self.assertEqual(len(mail.outbox), 0)

    def test_admin_can_edit_and_approve_a_flagged_account(self):
        user, review = self._pending_review(
            email="candidate@example.org",
            applicant_type=ManualReviewRequest.ApplicantType.STUDENT,
        )
        StudentProfile.objects.create(user=user, kezdes_eve=2023, szekcio="A")
        self.client.force_login(self.admin)

        page = self.client.get(reverse("manual-review-detail", args=[review.pk]))
        self.assertContains(page, "Jelentkező adatai")
        response = self.client.post(
            reverse("manual-review-detail", args=[review.pk]),
            self._review_data(
                "approve",
                applicant_type=ManualReviewRequest.ApplicantType.STUDENT,
                position="",
                om_id="7000012345",
                kezdes_eve="2023",
                szekcio="A",
            ),
        )

        self.assertRedirects(
            response,
            reverse("manual-review-list"),
            fetch_redirect_response=False,
        )
        user.refresh_from_db()
        review.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.email_verified)
        self.assertEqual(user.account_review_status, AccountReviewStatus.APPROVED)
        self.assertEqual(user.first_name, "Módosított")
        self.assertEqual(review.reviewed_by, self.admin)
        self.assertIsNotNone(review.reviewed_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [user.email])
        self.assertEqual(mail.outbox[0].alternatives[0][1], "text/html")
        self.assertIn("Fiók jóváhagyva", mail.outbox[0].alternatives[0][0])

        login = self.client.post(
            reverse("password-login"),
            {"email": user.email, "password": self.PASSWORD},
        )
        self.assertEqual(login.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)

    def test_admin_can_reject_and_the_rejection_email_uses_configured_contacts(self):
        user, review = self._pending_review()
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("manual-review-detail", args=[review.pk]),
            self._review_data("reject"),
        )

        self.assertRedirects(
            response,
            reverse("manual-review-list"),
            fetch_redirect_response=False,
        )
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertEqual(user.account_review_status, AccountReviewStatus.REJECTED)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [user.email])
        self.assertIn(self.admin.email, mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].alternatives[0][1], "text/html")
        self.assertIn(self.admin.email, mail.outbox[0].alternatives[0][0])

        denied = self.client.post(
            reverse("password-login"),
            {"email": user.email, "password": self.PASSWORD},
        )
        self.assertEqual(denied.status_code, 401)

    def test_only_staff_can_open_manual_review_dashboard(self):
        user = CustomUser.objects.create_user(
            email="ordinary@example.org", password=self.PASSWORD
        )
        self.client.force_login(user)

        response = self.client.get(reverse("manual-review-list"))

        self.assertEqual(response.status_code, 403)
