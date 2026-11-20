import math

from django.db import migrations

WORDS_PER_MINUTE = 200   # the default of CONTENT_READ_WORDS_PER_MINUTE; later saves use the configured value


def backfill(apps, schema_editor) -> None:  # noqa: ANN001
    ContentItem = apps.get_model('content', 'ContentItem')
    for item in ContentItem.objects.exclude(body='').only('content_id', 'body').iterator():
        words = len(item.body.split())
        if words:
            ContentItem.objects.filter(pk=item.pk).update(read_minutes=max(1, math.ceil(words / WORDS_PER_MINUTE)))


class Migration(migrations.Migration):
    dependencies = [('content', '0003_contentitem_duration_and_read_minutes')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
