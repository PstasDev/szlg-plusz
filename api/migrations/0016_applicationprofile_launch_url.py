from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0015_userappconnection"),
    ]

    operations = [
        migrations.AddField(
            model_name="applicationprofile",
            name="launch_url",
            field=models.URLField(
                blank=True,
                help_text="Az alkalmazás kezdőlapja, ahová a felhasználó az appcsempéről továbblép.",
                verbose_name="indítási URL",
            ),
        ),
    ]
