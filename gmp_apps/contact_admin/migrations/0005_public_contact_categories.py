from django.db import migrations

# The Contact Us dropdown: exactly these four, in this order.
PUBLIC_CATEGORIES = ['Membership', 'Schemes', 'Complaints', 'Any other']
OTHER_SORT_START = 100


def set_public_categories(apps, schema_editor) -> None:
    category = apps.get_model('contact_admin', 'ContactCategory')
    for order, name in enumerate(PUBLIC_CATEGORIES):
        category.objects.update_or_create(name=name, defaults={'sort_order': order, 'is_active': True})
    # Never deleted: existing requests point at them (the link is protected). They are only hidden.
    for offset, item in enumerate(category.objects.exclude(name__in=PUBLIC_CATEGORIES).order_by('sort_order', 'name')):
        item.is_active = False
        item.sort_order = OTHER_SORT_START + offset
        item.save(update_fields=['is_active', 'sort_order'])


class Migration(migrations.Migration):
    dependencies = [('contact_admin', '0004_guest_contact_requests')]
    operations = [migrations.RunPython(set_public_categories, migrations.RunPython.noop)]
