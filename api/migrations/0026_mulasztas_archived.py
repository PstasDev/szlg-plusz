from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0025_add_igazolas_undoed'),
    ]

    operations = [
        migrations.AddField(
            model_name='mulasztas',
            name='archived',
            field=models.BooleanField(default=False, help_text='A mulasztás archivált státuszban van', verbose_name='Archivált'),
        ),
        migrations.AddField(
            model_name='mulasztas',
            name='academic_year',
            field=models.CharField(blank=True, max_length=20, null=True, verbose_name='Tanév'),
        ),
    ]
