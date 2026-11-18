from django.db import migrations


def seed(apps, schema_editor) -> None:
    category = apps.get_model('content', 'ContentCategory')
    category.objects.get_or_create(name='General', defaults={'sort_order': 0})


class Migration(migrations.Migration):
    dependencies = [('content', '0001_initial')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
