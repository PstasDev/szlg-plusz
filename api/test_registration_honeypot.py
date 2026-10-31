from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import BotRegistrationAttempt


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class RegistrationHoneypotTests(TestCase):
    def test_registration_form_contains_the_hidden_honeypot(self):
        response = self.client.get(reverse("register"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="website"')
        self.assertContains(response, 'autocomplete="off"')
        self.assertContains(response, 'aria-hidden="true"')

    def test_filled_honeypot_is_logged_without_creating_an_account_or_sending_mail(self):
        response = self.client.post(
            reverse("register"),
            {
                "website": "https://spam.example/",
                "email": "bot@example.net",
                "first_name": "Robot",
                "last_name": "Account",
                "password1": "never-store-this-password",
                "password2": "never-store-this-password",
                "privacy_consent": "on",
                "csrfmiddlewaretoken": "secret-csrf-token",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Megerősítő levelet küldtünk")
        self.assertFalse(get_user_model().objects.filter(email="bot@example.net").exists())
        self.assertEqual(len(mail.outbox), 0)

        attempt = BotRegistrationAttempt.objects.get()
        self.assertEqual(attempt.form_data["email"], "bot@example.net")
        self.assertEqual(attempt.form_data["first_name"], "Robot")
        self.assertNotIn("password1", attempt.form_data)
        self.assertNotIn("password2", attempt.form_data)
        self.assertNotIn("website", attempt.form_data)
        self.assertNotIn("csrfmiddlewaretoken", attempt.form_data)
