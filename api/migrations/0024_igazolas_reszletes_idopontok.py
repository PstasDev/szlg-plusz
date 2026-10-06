from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0023_add_igazolas_image_field'),
    ]

    operations = [
        migrations.AddField(
            model_name='igazolas',
            name='reszletes_idopontok',
            field=models.JSONField(blank=True, help_text='Nem összefüggő hiányzás esetén az egyes részintervallumok listája', null=True, verbose_name='Részletes időpontok'),
        ),
    ]
