from django.contrib.auth.models import User
from django.db import models


class Passkey(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="passkeys")
    credential_id = models.BinaryField(unique=True)
    public_key = models.BinaryField()
    sign_count = models.BigIntegerField(default=0)
    transports = models.CharField(max_length=200, blank=True, default="")
    name = models.CharField(max_length=80, blank=True, default="Passkey")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.user.username} - {self.name}"

    class Meta:
        ordering = ["-created_at"]


class WebAuthnChallenge(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    challenge = models.CharField(max_length=512)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="webauthn_challenges",
        null=True,
        blank=True,
    )
    expires_at = models.DateTimeField(db_index=True)
