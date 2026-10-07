from django.db import migrations, models
from django.utils.text import slugify


def fill_slugs(apps, schema_editor):
    """Give every existing tagozat a unique slug derived from its name."""
    Tagozat = apps.get_model("api", "Tagozat")
    used = set()
    for tagozat in Tagozat.objects.order_by("pk"):
        base = slugify(tagozat.name)[:110] or "tagozat"
        slug, counter = base, 2
        while slug in used:
            slug = f"{base}-{counter}"
            counter += 1
        used.add(slug)
        tagozat.slug = slug
        tagozat.save(update_fields=["slug"])


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0011_jelkulcs_naming"),
    ]

    operations = [
        # 1) nullable and non-unique, so existing rows are accepted
        migrations.AddField(
            model_name="tagozat",
            name="slug",
            field=models.SlugField(max_length=120, null=True),
        ),
        # 2) populate existing rows
        migrations.RunPython(fill_slugs, migrations.RunPython.noop),
        # 3) enforce the final constraints
        migrations.AlterField(
            model_name="tagozat",
            name="slug",
            field=models.SlugField(max_length=120, unique=True),
        ),
    ]
