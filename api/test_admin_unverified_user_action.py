from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import GlobalConfig


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="sso@example.org",
)
class DeleteUnverifiedUsersAdminActionTests(TestCase):
    def setUp(self):
        config = GlobalConfig.get_solo()
        config.school_domain = "@school.example"
        config.save()

        user_model = get_user_model()
        self.admin_user = user_model.objects.create_superuser(
            email="admin@example.org", password="admin-password-123"
        )
        self.client.force_login(self.admin_user)

    def create_user(self, email, *, days_old, is_active=False, email_verified=False):
        user = get_user_model().objects.create_user(
            email=email,
            password="test-password-123",
            is_active=is_active,
            email_verified=email_verified,
        )
        user.date_joined = timezone.now() - timedelta(days=days_old)
        user.save(update_fields=["date_joined"])
        return user

    def select_action(self, users, **extra_data):
        data = {
            "action": "delete_unverified_users",
            "_selected_action": [str(user.pk) for user in users],
            "index": "0",
        }
        data.update(extra_data)
        return self.client.post(reverse("admin:api_customuser_changelist"), data)

    def test_action_only_lists_old_inactive_unverified_users_and_sends_notice(self):
        old_delete = self.create_user("delete@example.net", days_old=100)
        old_keep = self.create_user("keep@example.net", days_old=100)
        recent = self.create_user("recent@example.net", days_old=30)
        verified = self.create_user(
            "verified@example.net", days_old=100, email_verified=True
        )
        active = self.create_user(
            "active@example.net", days_old=100, is_active=True
        )

        response = self.select_action([old_delete, old_keep, recent, verified, active])

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, old_delete.email)
        self.assertContains(response, old_keep.email)
        self.assertNotContains(response, recent.email)
        self.assertNotContains(response, verified.email)
        self.assertNotContains(response, active.email)
        self.assertContains(response, 'name="keep_ids"')

        response = self.select_action(
            [old_delete, old_keep],
            user_ids=[str(old_delete.pk), str(old_keep.pk)],
            keep_ids=[str(old_keep.pk)],
            confirm="yes",
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(get_user_model().objects.filter(pk=old_delete.pk).exists())
        self.assertTrue(get_user_model().objects.filter(pk=old_keep.pk).exists())
        self.assertTrue(get_user_model().objects.filter(pk=recent.pk).exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [old_delete.email])
        self.assertIn("http://testserver/register/", mail.outbox[0].body)

    def test_account_verified_after_preview_is_not_deleted(self):
        user = self.create_user("changed@example.net", days_old=100)
        response = self.select_action([user])
        self.assertEqual(response.status_code, 200)

        user.email_verified = True
        user.save(update_fields=["email_verified"])
        response = self.select_action(
            [user], user_ids=[str(user.pk)], confirm="yes"
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(get_user_model().objects.filter(pk=user.pk).exists())
        self.assertEqual(len(mail.outbox), 0)
