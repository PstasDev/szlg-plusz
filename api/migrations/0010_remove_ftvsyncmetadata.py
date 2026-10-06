# Generated migration to remove FTVSyncMetadata model

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0009_osztaly_nem_fogadott_igazolas_tipusok'),
    ]

    operations = [
        migrations.DeleteModel(
            name='FTVSyncMetadata',
        ),
    ]
