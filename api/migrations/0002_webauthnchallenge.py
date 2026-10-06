import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WebAuthnChallenge",
            fields=[
                ("key", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("challenge", models.CharField(max_length=512)),
                ("expires_at", models.DateTimeField(db_index=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="webauthn_challenges",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
    ]
