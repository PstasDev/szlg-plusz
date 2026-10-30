from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AccountMigrationEmailAdminActionTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_superuser(
            email="admin@example.org", password="test-password-123"
        )
        self.client.force_login(self.admin_user)

    def test_action_sends_one_html_and_text_email_per_selected_user(self):
        users = [
            get_user_model().objects.create_user(email="first@example.org"),
            get_user_model().objects.create_user(email="second@example.org"),
        ]

        response = self.client.post(
            reverse("admin:api_customuser_changelist"),
            {
                "action": "send_szlg_plus_migration_notice",
                "_selected_action": [str(user.pk) for user in users],
                "index": "0",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(
            {tuple(message.to) for message in mail.outbox},
            {(user.email,) for user in users},
        )

        for message in mail.outbox:
            self.assertEqual(
                message.subject,
                "SZLG+ Fiókra állítottunk át az SZLG alkalmazásaiban.",
            )
            self.assertEqual(
                message.from_email,
                "SZLG Plusz <szlghonlap.ftv@gmail.com>",
            )
            self.assertEqual(len(message.alternatives), 1)
            html_body, mime_type = message.alternatives[0]
            self.assertEqual(mime_type, "text/html")
            self.assertIn("Mi az SZLG+?", html_body)
            self.assertIn("https://sso.szlg.info/adatvedelem/", html_body)
            self.assertIn("Kedves Felhasználók!", html_body)
            self.assertIn("Mi az SZLG+?", message.body)
