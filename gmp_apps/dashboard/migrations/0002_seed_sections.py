from django.db import migrations

SECTIONS = [
    ('profile', 'Profile'), ('membership', 'Membership and referrals'), ('announcements', 'Announcements'), ('posts', 'Posts'),
    ('videos', 'Videos'), ('tutorials', 'Tutorials'), ('org_updates', 'Organisation updates'), ('schemes', 'Government initiatives'),
    ('portals', 'Complaint portals'), ('support', 'Support messages'), ('notifications', 'Notifications'), ('chatbot', 'Chatbot'),
]


def seed(apps, schema_editor) -> None:
    section = apps.get_model('dashboard', 'DashboardSection')
    for index, (key, title) in enumerate(SECTIONS):
        section.objects.get_or_create(key=key, defaults={'title': title, 'sort_order': (index + 1) * 10})


class Migration(migrations.Migration):
    dependencies = [('dashboard', '0001_initial')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
