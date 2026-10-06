from django.contrib.auth.models import User
from django.test import TestCase

from .auth_challenges import consume_challenge


class AuthenticationAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="student",
            password="test-password-123",
            first_name="Test",
        )

    def login(self) -> str:
        response = self.client.post(
            "/api/auth/password/login",
            data={"username": "student", "password": "test-password-123"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["token"]

    def test_password_login_issues_jwt_and_me_returns_user(self):
        token = self.login()
        response = self.client.get(
            "/api/auth/me",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], self.user.username)

    def test_bad_password_does_not_issue_jwt(self):
        response = self.client.post(
            "/api/auth/password/login",
            data={"username": "student", "password": "wrong-password"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)

    def test_authenticated_user_can_list_passkeys_and_change_password(self):
        token = self.login()
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

        passkeys = self.client.get("/api/auth/passkeys", **headers)
        self.assertEqual(passkeys.status_code, 200)
        self.assertEqual(passkeys.json(), {"has_passkey": False, "passkeys": []})

        changed = self.client.post(
            "/api/auth/password/change",
            data={
                "old_password": "test-password-123",
                "new_password": "new-test-password-456",
            },
            content_type="application/json",
            **headers,
        )
        self.assertEqual(changed.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("new-test-password-456"))

    def test_password_change_uses_configured_password_validators(self):
        token = self.login()
        response = self.client.post(
            "/api/auth/password/change",
            data={"old_password": "test-password-123", "new_password": "test"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json()["detail"])

    def test_passkey_login_options_are_public(self):
        response = self.client.post(
            "/api/auth/passkeys/login/options",
            data={},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("challenge_id", response.json())
        self.assertIn("options", response.json())
        challenge_key = f"passkey:auth:{response.json()['challenge_id']}"
        self.assertIsNotNone(consume_challenge(challenge_key))
        self.assertIsNone(consume_challenge(challenge_key))
