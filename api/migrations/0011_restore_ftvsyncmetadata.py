# Generated manually to restore FTVSyncMetadata model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0010_remove_ftvsyncmetadata'),
    ]

    operations = [
        migrations.CreateModel(
            name='FTVSyncMetadata',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sync_type', models.CharField(max_length=100, unique=True)),  # 'base', 'user_{id}', 'class_{id}'
                ('last_sync_time', models.DateTimeField(blank=True, null=True)),
                ('last_sync_status', models.CharField(default='never', max_length=20)),
                ('last_sync_stats', models.JSONField(blank=True, null=True)),
            ],
            options={
                'verbose_name': 'FTV Sync Metadata',
                'verbose_name_plural': 'FTV Sync Metadata',
            },
        ),
    ]
