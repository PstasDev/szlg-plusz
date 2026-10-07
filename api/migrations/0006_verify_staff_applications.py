from django.db import migrations


def verify_staff_applications(apps, schema_editor):
    """Applications registered by staff before self-service existed are trusted."""
    Application = apps.get_model("oauth2_provider", "Application")
    ApplicationProfile = apps.get_model("api", "ApplicationProfile")
    staff_applications = Application.objects.filter(user__is_staff=True)
    ApplicationProfile.objects.filter(application__in=staff_applications).update(verified=True)


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0005_applicationprofile_verified"),
    ]

    operations = [
        migrations.RunPython(verify_staff_applications, migrations.RunPython.noop),
    ]
