# Generated migration for TanitasiSzunet and Override models

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0012_systemmessage'),
    ]

    operations = [
        migrations.CreateModel(
            name='TanitasiSzunet',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('type', models.CharField(choices=[('oszi', 'Őszi szünet'), ('teli', 'Téli szünet'), ('tavaszi', 'Tavaszi szünet'), ('nyari', 'Nyári szünet'), ('erettsegi', 'Érettségi időszak'), ('digitalis', 'Digitális oktatás'), ('egyeb', 'Egyéb')], help_text='A tanítási szünet típusa', max_length=20, verbose_name='Típus')),
                ('name', models.CharField(blank=True, help_text='Egyedi név a szünetnek (opcionális)', max_length=200, null=True, verbose_name='Név')),
                ('from_date', models.DateField(help_text='A tanítási szünet kezdő dátuma', verbose_name='Kezdő dátum')),
                ('to_date', models.DateField(help_text='A tanítási szünet záró dátuma', verbose_name='Záró dátum')),
                ('description', models.TextField(blank=True, help_text='Megjegyzések vagy további információk a szünetről', max_length=1000, null=True, verbose_name='Leírás')),
            ],
            options={
                'verbose_name': 'Tanítási Szünet',
                'verbose_name_plural': 'Tanítási Szünetek',
                'ordering': ['from_date'],
            },
        ),
        migrations.CreateModel(
            name='Override',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(help_text='A kivétel dátuma', verbose_name='Dátum')),
                ('is_required', models.BooleanField(help_text='True = jelenlét kötelező, False = jelenlét nem kötelező', verbose_name='Jelenléti kötelezettség')),
                ('reason', models.TextField(blank=True, help_text='A kivétel indoklása vagy megjegyzések', max_length=1000, null=True, verbose_name='Indoklás')),
                ('class_id', models.ForeignKey(blank=True, help_text='Ha megadva, csak erre az osztályra vonatkozik. Ha üres, minden osztályra vonatkozik.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='overrides', to='api.osztaly', verbose_name='Osztály')),
            ],
            options={
                'verbose_name': 'Kivétel (Override)',
                'verbose_name_plural': 'Kivételek (Overrides)',
                'ordering': ['date'],
            },
        ),
    ]
