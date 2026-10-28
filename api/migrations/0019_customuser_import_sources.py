from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0018_registration_privacy_contacts"),
    ]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="import_sources",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text=(
                    "Azon alkalmazások neve és stabil azonosítója, amelyekből a fiók adatait "
                    "importáltuk. Az importáló felület bővíti, nem cseréli le a listát."
                ),
                verbose_name="adatimport-források",
            ),
        ),
    ]
