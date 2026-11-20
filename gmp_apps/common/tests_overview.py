from datetime import timedelta
from io import StringIO

from django.contrib.auth.models import Group, Permission
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from gmp.config import Configurations
from gmp_apps.authentication.management.commands.setup_admin_groups import GROUPS
from gmp_apps.authentication.models import User
from gmp_apps.chatbot.models import KnowledgeEntry
from gmp_apps.content.models import ContentCategory, ContentItem
from gmp_apps.schemes.models import Scheme, SchemeSyncRun

PASSWORD = 'Sunrise#Valley42'
FAST_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
NEW_TITLES = {
    'Approved chatbot entries', 'Scheduled content', 'Schemes waiting for pictures/PDFs', 'Last scheme sync', 'Next scheme sync (about)',
}


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class OverviewBase(TestCase):
    def setUp(self) -> None:
        cache.clear()
        call_command('setup_admin_groups', stdout=StringIO())
        self.counter = 0

    def staff(self, *groups: str) -> User:
        self.counter += 1
        user = User.objects.create_user(full_name='Staff', password=PASSWORD, email=f's{self.counter}@example.com', is_staff=True, role='admin', email_verified=True)
        user.groups.add(*Group.objects.filter(name__in=groups))
        return user

    def cards(self, user: User) -> dict[str, dict]:
        client = Client()
        client.force_login(user)
        return {c['title']: c for c in client.get('/admin/').context['dashboard_cards']}


class OverviewCardTests(OverviewBase):
    def setUp(self) -> None:
        super().setUp()
        self.root = User.objects.create_superuser(full_name='Root', password=PASSWORD, email='root@example.com')

    def test_counts_are_right(self) -> None:
        KnowledgeEntry.objects.create(question='a', answer='b', status='approved')
        KnowledgeEntry.objects.create(question='c', answer='d', status='draft')
        KnowledgeEntry.objects.create(question='e', answer='f', status='retired')
        category = ContentCategory.objects.create(name='News')
        now = timezone.now()
        ContentItem.objects.create(title='live', body='x', category=category, status='published', publish_at=now - timedelta(hours=1))
        ContentItem.objects.create(title='later', body='x', category=category, status='published', publish_at=now + timedelta(days=1))
        ContentItem.objects.create(title='later too', body='x', category=category, status='published', publish_at=now + timedelta(days=2))
        ContentItem.objects.create(title='draft', body='x', category=category, status='draft', publish_at=now + timedelta(days=1))
        Scheme.objects.create(title='waiting', source_url='https://www.govtschemes.in/w')
        Scheme.objects.create(title='waiting 2', source_url='https://www.govtschemes.in/w2')
        Scheme.objects.create(title='waiting 3', source_url='https://www.govtschemes.in/w3')
        Scheme.objects.create(title='verified', source_url='https://www.govtschemes.in/v', media_synced_at=now)
        Scheme.objects.create(title='manual', is_manual=True)
        Scheme.objects.create(title='edited', source_url='https://www.govtschemes.in/e', locally_edited=True)
        cards = self.cards(self.root)
        self.assertEqual(cards['Approved chatbot entries']['value'], 1)
        self.assertEqual(cards['Chatbot entries awaiting approval']['value'], 1)
        self.assertEqual(cards['Scheduled content']['value'], 2)
        self.assertEqual(cards['Live content']['value'], 1)
        self.assertEqual(cards['Schemes waiting for pictures/PDFs']['value'], 3)

    def test_cards_link_to_lists_that_show_exactly_those_rows(self) -> None:
        KnowledgeEntry.objects.create(question='a', answer='b', status='approved')
        category = ContentCategory.objects.create(name='News')
        later = timezone.now() + timedelta(days=1)
        ContentItem.objects.create(title='later', body='x', category=category, status='published', publish_at=later)
        Scheme.objects.create(title='waiting', source_url='https://www.govtschemes.in/w')
        Scheme.objects.create(title='verified', source_url='https://www.govtschemes.in/v', media_synced_at=timezone.now())
        client = Client()
        client.force_login(self.root)
        cards = self.cards(self.root)
        for title in ('Approved chatbot entries', 'Scheduled content', 'Schemes waiting for pictures/PDFs'):
            response = client.get(cards[title]['link'])
            self.assertEqual(response.status_code, 200, title)
            self.assertEqual(len(response.context['cl'].result_list), 1, title)
            self.assertEqual(response.context['cl'].result_list[0].__class__.__name__ in ('KnowledgeEntry', 'ContentItem', 'Scheme'), True)

    def test_sync_cards_when_never_run(self) -> None:
        cards = self.cards(self.root)
        self.assertEqual(cards['Last scheme sync']['value'], 'Never run')
        self.assertNotIn('Next scheme sync (about)', cards)

    def test_sync_cards_show_the_latest_run_and_the_next_due_time(self) -> None:
        old = SchemeSyncRun.objects.create(status='failed')
        SchemeSyncRun.objects.filter(pk=old.pk).update(started_date_time=timezone.now() - timedelta(days=3))
        latest = SchemeSyncRun.objects.create(status='partial')
        cards = self.cards(self.root)
        started = timezone.localtime(latest.started_date_time)
        self.assertEqual(cards['Last scheme sync']['value'], f'Finished with errors, {started:%d %b %H:%M}')
        due = started + timedelta(hours=Configurations.scheme_sync_interval_hours)
        self.assertEqual(cards['Next scheme sync (about)']['value'], f'{due:%d %b %H:%M}')
        self.assertTrue(cards['Last scheme sync']['link'].endswith('/admin/schemes/schemesyncrun/'))

    def test_each_group_sees_only_its_own_new_cards(self) -> None:
        expected = {
            'Scheme Reviewers': {'Schemes waiting for pictures/PDFs', 'Last scheme sync'},
            'Knowledge Editors': {'Approved chatbot entries'},
            'Knowledge Approvers': {'Approved chatbot entries'},
            'Content Editors': {'Scheduled content'}, 'Content Publishers': {'Scheduled content'},
            'Support Handlers': set(), 'Portal Managers': set(), 'Member Managers': set(), 'Membership Reviewers': set(), 'Dashboard Managers': set(),
            'Document Reviewers': set(), 'Identity Reviewers': set(), 'App Text Editors': set(),
        }
        for group, wanted in expected.items():
            seen = set(self.cards(self.staff(group))) & NEW_TITLES
            self.assertEqual(seen, wanted, group)

    def test_no_cards_contain_personal_data(self) -> None:
        User.objects.create_user(full_name='Asha Verma', password=PASSWORD, email='asha@example.com', email_verified=True)
        text = str(self.cards(self.root))
        for private in ('Asha', 'asha@example.com'):
            self.assertNotIn(private, text)


class PermissionMatrixTests(OverviewBase):
    """The reviewed access plan, pinned. A change to who can do what must change this test on purpose."""

    EXPECTED = {
        'Member Managers': {'authentication.view_user', 'authentication.change_user', 'authentication.suspend_member'},
        'Membership Reviewers': {f'membership.{a}_{m}' for a in ('view', 'change') for m in ('referral', 'permanentapplication', 'referralinvite')},
        'Scheme Reviewers': {f'schemes.{a}_{m}' for a in ('view', 'add', 'change', 'delete') for m in ('scheme', 'schemetag', 'schemeimage', 'schemedocument')}
        | {'schemes.publish_scheme', 'schemes.run_scheme_sync', 'schemes.view_schemeexclusion', 'schemes.delete_schemeexclusion', 'schemes.view_schemesyncrun'},
        'Knowledge Editors': {'chatbot.view_knowledgeentry', 'chatbot.add_knowledgeentry', 'chatbot.change_knowledgeentry'},
        'Knowledge Approvers': {'chatbot.view_knowledgeentry', 'chatbot.add_knowledgeentry', 'chatbot.change_knowledgeentry',
                                'chatbot.delete_knowledgeentry', 'chatbot.approve_knowledgeentry', 'chatbot.view_chatlog'},
        'Dashboard Managers': {'dashboard.view_dashboardsection', 'dashboard.change_dashboardsection'},
        'App Text Editors': {f'app_text.{a}_apptext' for a in ('view', 'add', 'change', 'delete')},
        'Document Reviewers': {'member_documents.view_memberdocument', 'member_documents.download_memberdocument'},
        'Identity Reviewers': {'authentication.view_user', 'authentication.view_government_ids'},
        'Content Editors': {f'content.{a}_{m}' for a in ('view', 'add', 'change') for m in ('contentitem', 'contentcategory')},
        'Content Publishers': {f'content.{a}_{m}' for a in ('view', 'add', 'change', 'delete') for m in ('contentitem', 'contentcategory')} | {'content.publish_contentitem'},
        'Portal Managers': {f'portals.{a}_{m}' for a in ('view', 'add', 'change', 'delete') for m in ('complaintportal', 'portalcategory')},
        'Support Handlers': {'contact_admin.view_contactrequest', 'contact_admin.change_contactrequest',
                             'contact_admin.view_contactcategory', 'contact_admin.add_contactcategory', 'contact_admin.change_contactcategory'},
    }

    @staticmethod
    def granted(name: str) -> set[str]:
        return {f'{p.content_type.app_label}.{p.codename}' for p in Group.objects.get(name=name).permissions.select_related('content_type')}

    def test_every_group_has_exactly_its_reviewed_permissions(self) -> None:
        self.assertEqual(set(GROUPS), set(self.EXPECTED))
        self.assertEqual(set(Group.objects.values_list('name', flat=True)), set(self.EXPECTED))
        for name, wanted in self.EXPECTED.items():
            self.assertEqual(self.granted(name), wanted, name)

    def test_setup_is_repeatable_and_removes_drift(self) -> None:
        group = Group.objects.get(name='Support Handlers')
        group.permissions.add(Permission.objects.get(codename='delete_user'))
        call_command('setup_admin_groups', stdout=StringIO())
        call_command('setup_admin_groups', stdout=StringIO())
        self.assertEqual(self.granted('Support Handlers'), self.EXPECTED['Support Handlers'])

    def test_sensitive_permissions_sit_only_in_their_designated_groups(self) -> None:
        sensitive = {
            'publish_scheme': {'Scheme Reviewers'}, 'publish_contentitem': {'Content Publishers'}, 'approve_knowledgeentry': {'Knowledge Approvers'},
            'suspend_member': {'Member Managers'}, 'run_scheme_sync': {'Scheme Reviewers'}, 'view_chatlog': {'Knowledge Approvers'},
            'download_memberdocument': {'Document Reviewers'}, 'view_government_ids': {'Identity Reviewers'}, 'view_memberdocument': {'Document Reviewers'}, 'delete_memberdocument': set(),
            'view_memberdocumentaccesslog': set(),
            'delete_user': set(), 'add_user': set(), 'view_group': set(), 'change_group': set(), 'add_group': set(), 'change_permission': set(),
        }
        for codename, groups in sensitive.items():
            holders = {name for name in self.EXPECTED if any(p.endswith(f'.{codename}') for p in self.granted(name))}
            self.assertEqual(holders, groups, codename)

    def test_nobody_but_a_superuser_touches_accounts_roles_or_tokens(self) -> None:
        forbidden_apps = {'auth', 'admin', 'sessions', 'contenttypes', 'token_blacklist'}
        for name in self.EXPECTED:
            self.assertFalse({p.split('.')[0] for p in self.granted(name)} & forbidden_apps, name)
            self.assertFalse({p for p in self.granted(name) if p.startswith('authentication.') and not p.endswith(('view_user', 'change_user', 'suspend_member', 'view_government_ids'))}, name)

    def test_makers_never_hold_more_than_checkers_in_the_same_area(self) -> None:
        self.assertLess(self.granted('Knowledge Editors'), self.granted('Knowledge Approvers'))
        self.assertLess(self.granted('Content Editors'), self.granted('Content Publishers'))
        self.assertFalse({p for p in self.granted('Content Editors') | self.granted('Knowledge Editors') if p.split('.')[1].startswith(('delete_', 'publish_', 'approve_'))})

    def test_groups_do_not_reach_into_each_others_areas(self) -> None:
        areas = {'Member Managers': 'authentication', 'Membership Reviewers': 'membership', 'Scheme Reviewers': 'schemes', 'Knowledge Editors': 'chatbot',
                 'Knowledge Approvers': 'chatbot', 'Dashboard Managers': 'dashboard', 'Content Editors': 'content', 'Content Publishers': 'content',
                 'Portal Managers': 'portals', 'Support Handlers': 'contact_admin', 'Document Reviewers': 'member_documents', 'Identity Reviewers': 'authentication', 'App Text Editors': 'app_text'}
        for name, app in areas.items():
            self.assertEqual({p.split('.')[0] for p in self.granted(name)}, {app}, name)

    def test_staff_without_a_group_can_open_nothing(self) -> None:
        nobody = self.staff()
        client = Client()
        client.force_login(nobody)
        for path in ('/admin/authentication/user/', '/admin/schemes/scheme/', '/admin/content/contentitem/', '/admin/chatbot/knowledgeentry/',
                     '/admin/portals/complaintportal/', '/admin/contact_admin/contactrequest/', '/admin/dashboard/dashboardsection/',
                     '/admin/schemes/schemesyncrun/', '/admin/chatbot/chatlog/', '/admin/auth/group/', '/admin/member_documents/memberdocument/',
                     '/admin/member_documents/memberdocumentaccesslog/', '/admin/authentication/governmentidaccesslog/'):
            self.assertEqual(client.get(path).status_code, 403, path)
        self.assertEqual(self.cards(nobody), {})
