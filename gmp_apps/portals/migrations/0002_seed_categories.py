from django.db import migrations

DEFAULT_CATEGORIES = ['General', 'Other']


def seed(apps, schema_editor) -> None:
    category = apps.get_model('portals', 'PortalCategory')
    for order, name in enumerate(DEFAULT_CATEGORIES):
        category.objects.get_or_create(name=name, defaults={'sort_order': order})


class Migration(migrations.Migration):
    dependencies = [('portals', '0001_initial')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
