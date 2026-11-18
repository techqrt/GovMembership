import atexit
import shutil
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.db import connection
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from gmp.config import Configurations
from gmp_apps.authentication.models import User
from gmp_apps.contact_admin.models import ContactCategory, ContactRequest
from gmp_apps.content.models import ContentCategory, ContentItem
from gmp_apps.dashboard import builders
from gmp_apps.dashboard.models import DashboardSection
from gmp_apps.membership.models import PermanentApplication, Referral
from gmp_apps.notifications.models import Notification
from gmp_apps.portals.models import ComplaintPortal, PortalCategory
from gmp_apps.schemes.models import Scheme, SchemeImage

PASSWORD = 'Sunrise#Valley42'
FAST_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
MEDIA_TMP = tempfile.mkdtemp(prefix='gmp-test-dashboard-')
atexit.register(shutil.rmtree, MEDIA_TMP, ignore_errors=True)
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 40
HOUR = timedelta(hours=1)
ALL_KEYS = ['profile', 'membership', 'announcements', 'posts', 'videos', 'tutorials', 'org_updates', 'schemes', 'portals', 'support', 'notifications', 'chatbot']


def clean_media() -> None:
    for folder in ('schemes', 'content'):
        shutil.rmtree(Path(MEDIA_TMP) / folder, ignore_errors=True)


@override_settings(PASSWORD_HASHERS=FAST_HASHERS, MEDIA_ROOT=MEDIA_TMP)
class DashboardBase(APITestCase):
    def setUp(self) -> None:
        clean_media()
        self.addCleanup(clean_media)
        cache.clear()
        call_command('setup_admin_groups', stdout=StringIO())
        self.counter = 0
        self.general_cat = ContentCategory.objects.get(name='General')

    def member(self, level: str = 'general', **extra) -> User:
        self.counter += 1
        return User.objects.create_user(full_name=f'Member Number{self.counter}', password=PASSWORD, email=f'm{self.counter}@example.com',
                                        email_verified=True, membership_level=level, **extra)

    def staff(self, *groups: str, role: str = 'admin') -> User:
        self.counter += 1
        user = User.objects.create_user(full_name='Staff', password=PASSWORD, email=f's{self.counter}@example.com', is_staff=True, role=role, email_verified=True)
        user.groups.add(*Group.objects.filter(name__in=groups))
        return user

    @staticmethod
    def as_user(user: User | None) -> APIClient:
        client = APIClient()
        if user:
            client.force_authenticate(user)
        return client

    def content(self, title: str, content_type: str = 'post', min_level: str = 'general', **extra) -> ContentItem:
        defaults = {'body': 'text', 'summary': f'About {title}', 'category': self.general_cat, 'status': 'published', 'publish_at': timezone.now() - HOUR}
        defaults.update(extra)
        return ContentItem.objects.create(title=title, content_type=content_type, min_level=min_level, **defaults)

    def scheme(self, title: str = 'Scheme', status: str = 'published', **extra) -> Scheme:
        return Scheme.objects.create(title=title, description=f'About {title}', status=status, source_url=f'https://www.govtschemes.in/{title.lower().replace(" ", "-")}', **extra)

    def portal(self, name: str, **extra) -> ComplaintPortal:
        self.counter += 1
        extra.setdefault('category', PortalCategory.objects.get(name='General'))
        return ComplaintPortal.objects.create(name=name, official_url=f'https://portal{self.counter}.gov.in', **extra)

    def request(self, member: User, subject: str = 'Help', status: str = 'open', reply: str = '') -> ContactRequest:
        return ContactRequest.objects.create(user=member, category=ContactCategory.objects.first(), subject=subject, description='A long enough description.',
                                             status=status, admin_reply=reply)

    def dashboard(self, member: User, **headers) -> dict:
        response = self.as_user(member).get('/dashboard/get/', **headers)
        self.assertEqual(response.status_code, 200, response.data)
        return {s['key']: s for s in response.data['data']['sections']}

    def keys(self, member: User) -> list[str]:
        return [s['key'] for s in self.as_user(member).get('/dashboard/get/').data['data']['sections']]


class SectionSettingsTests(DashboardBase):
    def test_all_twelve_sections_are_seeded_in_order_with_profile_and_membership_first(self) -> None:
        self.assertEqual(list(DashboardSection.objects.values_list('key', flat=True)), ALL_KEYS)
        self.assertTrue(all(s.is_enabled and s.min_level == 'general' for s in DashboardSection.objects.all()))

    def test_profile_and_membership_cannot_be_switched_off_or_restricted(self) -> None:
        for key in ('profile', 'membership'):
            section = DashboardSection.objects.get(key=key)
            for change in ({'is_enabled': False}, {'min_level': 'active'}, {'min_level': 'permanent'}):
                for field, value in change.items():
                    setattr(section, field, value)
                with self.assertRaises(ValidationError):
                    section.full_clean()
                with self.assertRaises(ValidationError):
                    section.save()
                section.refresh_from_db()
        other = DashboardSection.objects.get(key='videos')
        other.is_enabled, other.min_level = False, 'permanent'
        other.save()


class DashboardApiTests(DashboardBase):
    def test_every_section_in_admin_order_with_the_expected_shape(self) -> None:
        sections = self.dashboard(self.member())
        self.assertEqual(list(sections), ALL_KEYS)
        self.assertEqual(sections['profile']['title'], 'Profile')
        for key in ('announcements', 'posts', 'videos', 'tutorials', 'org_updates', 'schemes', 'portals'):
            self.assertEqual(set(sections[key]['data']), {'total', 'items'}, key)
        self.assertEqual(set(sections['support']['data']), {'openRequests', 'latest'})
        self.assertEqual(set(sections['notifications']['data']), {'unreadCount', 'latest'})
        self.assertEqual(sections['chatbot']['data'], {'available': False})

    def test_authentication_and_roles(self) -> None:
        self.assertEqual(self.as_user(None).get('/dashboard/get/').status_code, 401)
        self.assertEqual(self.as_user(self.staff('Content Publishers')).get('/dashboard/get/').status_code, 403)
        for method in ('post', 'put', 'patch', 'delete'):
            self.assertEqual(getattr(self.as_user(self.member()), method)('/dashboard/get/', {}, format='json').status_code, 405, method)

    def test_a_suspended_member_loses_access(self) -> None:
        member = self.member()
        token = APIClient().post('/auth/login/', {'identifier': member.email, 'password': PASSWORD}, format='json').data['data']['access']
        self.assertEqual(APIClient().get('/dashboard/get/', HTTP_AUTHORIZATION=f'Bearer {token}').status_code, 200)
        User.objects.filter(pk=member.pk).update(is_active=False)
        self.assertEqual(APIClient().get('/dashboard/get/', HTTP_AUTHORIZATION=f'Bearer {token}').status_code, 401)

    def test_profile_and_membership_are_the_callers_own_and_match_the_progress_endpoint(self) -> None:
        member = self.member('active', mobile_number='9876543210')
        for _ in range(2):
            Referral.objects.create(referrer=member, referred=self.member(), status='verified')
        PermanentApplication.objects.create(user=member, reason='x' * 20)
        sections = self.dashboard(member)
        profile = sections['profile']['data']
        self.assertEqual((profile['membershipId'], profile['fullName'], profile['membershipLevel'], profile['mobileNumber']),
                         (member.membership_id, member.full_name, 'active', '9876543210'))
        for internal in ('password', 'role', 'userId', 'isStaff', 'registrationIp', 'referralCode'):
            self.assertNotIn(internal, profile)
        progress = self.as_user(member).get('/membership/progress/get/').data['data']
        self.assertEqual(sections['membership']['data'], progress)
        self.assertEqual((progress['verifiedReferrals'], progress['permanentApplication']['status']), (2, 'pending'))

    def test_two_members_never_see_each_others_data(self) -> None:
        one, two = self.member(), self.member()
        self.request(one, subject='Only mine one')
        self.request(two, subject='Only mine two')
        Notification.send(one.user_id, 'support_update', 'For one', 'm')
        Notification.send(two.user_id, 'support_update', 'For two', 'm')
        Referral.objects.create(referrer=two, referred=self.member(), status='verified')
        first, second = self.dashboard(one), self.dashboard(two)
        self.assertEqual([r['subject'] for r in first['support']['data']['latest']], ['Only mine one'])
        self.assertEqual([r['subject'] for r in second['support']['data']['latest']], ['Only mine two'])
        self.assertEqual([n['title'] for n in first['notifications']['data']['latest']], ['For one'])
        self.assertEqual(first['membership']['data']['verifiedReferrals'], 0)
        self.assertEqual(second['membership']['data']['verifiedReferrals'], 1)
        blob = str(first)
        for private in (two.full_name, two.email, two.membership_id, 'Only mine two', 'For two'):
            self.assertNotIn(private, blob)

    def test_content_sections_follow_type_level_schedule_and_category(self) -> None:
        now = timezone.now()
        self.content('Notice', 'announcement')
        self.content('Post for everyone', 'post')
        self.content('Post for active', 'post', min_level='active')
        self.content('Clip', 'video', video_url='https://youtu.be/abc')
        self.content('Guide', 'tutorial')
        self.content('News', 'org_update')
        self.content('Scheduled post', 'post', publish_at=now + HOUR)
        self.content('Expired post', 'post', publish_at=now - 3 * HOUR, expire_at=now - HOUR)
        self.content('Draft post', 'post', status='draft', publish_at=None)
        self.content('Off category', 'post', category=ContentCategory.objects.create(name='Off', is_active=False))
        general = self.dashboard(self.member('general'))
        titles = lambda key: [i['title'] for i in general[key]['data']['items']]   # noqa: E731
        self.assertEqual(titles('posts'), ['Post for everyone'])
        self.assertEqual((titles('announcements'), titles('videos'), titles('tutorials'), titles('org_updates')), (['Notice'], ['Clip'], ['Guide'], ['News']))
        self.assertEqual(general['posts']['data']['total'], 1)
        active = self.dashboard(self.member('active'))
        self.assertEqual(sorted(i['title'] for i in active['posts']['data']['items']), ['Post for active', 'Post for everyone'])
        self.assertEqual(active['posts']['data']['total'], 2)
        for hidden in ('Scheduled post', 'Expired post', 'Draft post', 'Off category'):
            self.assertNotIn(hidden, str(general) + str(active))

    def test_items_are_capped_with_the_true_total_and_pinned_first(self) -> None:
        for index in range(7):
            self.content(f'Post {index}', 'post', publish_at=timezone.now() - (index + 1) * HOUR)
        self.content('Pinned old', 'post', is_pinned=True, publish_at=timezone.now() - 20 * HOUR)
        with mock.patch.object(Configurations, 'dashboard_items_per_section', 3):
            section = self.dashboard(self.member())['posts']['data']
        self.assertEqual((section['total'], len(section['items'])), (8, 3))
        self.assertEqual([i['title'] for i in section['items']], ['Pinned old', 'Post 0', 'Post 1'])

    def test_content_rows_match_the_content_api_and_expose_nothing_internal(self) -> None:
        item = self.content('Shape', 'post', min_level='general', expire_at=timezone.now() + 5 * HOUR)
        item.cover_image = ContentFile(PNG, name='x.png')
        item.save()
        member = self.member()
        row = self.dashboard(member)['posts']['data']['items'][0]
        api = self.as_user(member).get('/content/get_all/', HTTP_HOST='testserver').data['data']['data'][0]
        self.assertEqual(row, api)
        self.assertNotIn('body', row)
        self.assertEqual(row['coverImageUrl'], f'http://testserver{item.cover_image.url}')
        for internal in ('status', 'minLevel', 'expireAt', 'createdBy'):
            self.assertNotIn(internal, str(row))

    def test_schemes_are_published_only_with_our_own_image_urls_and_no_source(self) -> None:
        live = self.scheme('Live scheme')
        SchemeImage.objects.create(scheme=live, file=ContentFile(PNG, name='x'), source_url='https://www.govtschemes.in/sites/default/files/a.png')
        self.scheme('Pending scheme', status='pending_review')
        self.scheme('Hidden scheme', status='unpublished')
        section = self.dashboard(self.member())['schemes']
        self.assertEqual((section['data']['total'], [i['title'] for i in section['data']['items']]), (1, ['Live scheme']))
        self.assertTrue(section['data']['items'][0]['imageUrl'].startswith('http://testserver/media/schemes/'))
        text = str(section).lower()
        self.assertNotIn('govtschemes', text)
        self.assertNotIn('sourceurl', text)

    def test_portals_show_active_ones_in_active_categories(self) -> None:
        self.portal('Listed')
        self.portal('Off', is_active=False)
        self.portal('In off category', category=PortalCategory.objects.create(name='Gone', is_active=False))
        section = self.dashboard(self.member())['portals']['data']
        self.assertEqual((section['total'], [p['name'] for p in section['items']]), (1, ['Listed']))
        self.assertIn('officialUrl', section['items'][0])

    def test_support_section_counts_open_requests_and_hides_admin_identity(self) -> None:
        member = self.member()
        for index in range(5):
            self.request(member, subject=f'Request {index}', status='open')
        self.request(member, subject='Answered', status='resolved', reply='Done')
        section = self.dashboard(member)['support']['data']
        self.assertEqual((section['openRequests'], len(section['latest'])), (5, Configurations.dashboard_support_items))
        self.assertEqual(section['latest'][0]['subject'], 'Answered')
        self.assertTrue(section['latest'][0]['hasReply'])
        self.assertEqual(set(section['latest'][0]), {'requestId', 'subject', 'categoryName', 'status', 'hasReply', 'repliedDateTime', 'createdDateTime'})

    def test_notifications_section_counts_unread_and_lists_latest(self) -> None:
        member = self.member()
        for index in range(7):
            Notification.send(member.user_id, 'support_update', f'Note {index}', 'm')
        Notification.mark_read(member.user_id, Notification.objects.filter(user=member).first().notification_id)
        section = self.dashboard(member)['notifications']['data']
        self.assertEqual((section['unreadCount'], len(section['latest'])), (6, Configurations.dashboard_items_per_section))
        self.assertEqual(section['latest'][0]['title'], 'Note 6')

    def test_chatbot_availability_is_a_switch(self) -> None:
        member = self.member()
        with mock.patch('gmp_apps.dashboard.builders.is_available', return_value=True):
            self.assertEqual(self.dashboard(member)['chatbot']['data'], {'available': True})

    def test_a_promotion_changes_the_dashboard_immediately(self) -> None:
        member = self.member('general')
        self.content('Active guide', 'tutorial', min_level='active')
        self.assertEqual(self.dashboard(member)['tutorials']['data']['total'], 0)
        User.objects.filter(pk=member.pk).update(membership_level='active')
        self.assertEqual(self.dashboard(member)['tutorials']['data']['total'], 1)


class AdminControlTests(DashboardBase):
    def test_a_switched_off_section_disappears_and_is_not_even_built(self) -> None:
        DashboardSection.objects.filter(key__in=['videos', 'portals']).update(is_enabled=False)
        member = self.member()
        with mock.patch.dict(builders.BUILDERS, {'videos': mock.Mock(side_effect=AssertionError('built')), 'portals': mock.Mock(side_effect=AssertionError('built'))}):
            keys = self.keys(member)
        self.assertEqual(keys, [k for k in ALL_KEYS if k not in ('videos', 'portals')])

    def test_minimum_level_per_section(self) -> None:
        DashboardSection.objects.filter(key='tutorials').update(min_level='active')
        DashboardSection.objects.filter(key='schemes').update(min_level='permanent')
        self.assertEqual(set(ALL_KEYS) - set(self.keys(self.member('general'))), {'tutorials', 'schemes'})
        self.assertEqual(set(ALL_KEYS) - set(self.keys(self.member('active'))), {'schemes'})
        self.assertEqual(self.keys(self.member('permanent')), ALL_KEYS)

    def test_admin_order_is_respected(self) -> None:
        DashboardSection.objects.filter(key='notifications').update(sort_order=1)
        DashboardSection.objects.filter(key='posts').update(sort_order=2)
        self.assertEqual(self.keys(self.member())[:4], ['notifications', 'posts', 'profile', 'membership'])

    def test_a_restricted_section_is_not_mentioned_to_lower_levels(self) -> None:
        DashboardSection.objects.filter(key='portals').update(min_level='active')
        self.content('Post', 'post')
        blob = str(self.as_user(self.member('general')).get('/dashboard/get/').data)
        self.assertNotIn('portals', blob)
        self.assertNotIn('Complaint portals', blob)

    def test_query_count_does_not_grow_with_the_amount_of_data(self) -> None:
        member = self.member('permanent')
        client = self.as_user(member)
        counter = {'n': 0}

        def add_one_of_everything() -> None:
            counter['n'] += 1
            index = counter['n']
            for kind in ('announcement', 'post', 'video', 'tutorial', 'org_update'):
                self.content(f'{kind} {index}', kind, video_url='https://youtu.be/abc' if kind == 'video' else '')
            scheme = self.scheme(f'Scheme {index}')
            SchemeImage.objects.create(scheme=scheme, file=ContentFile(PNG + str(index).encode(), name='x'))
            self.portal(f'Portal {index}')
            self.request(member, subject=f'R{index}')
            Notification.send(member.user_id, 'support_update', f'N{index}', 'm')
            Referral.objects.create(referrer=member, referred=self.member(), status='verified')

        add_one_of_everything()   # not empty: Django skips prefetch queries for empty result sets
        with CaptureQueriesContext(connection) as small:
            client.get('/dashboard/get/')
        for _ in range(24):
            add_one_of_everything()
        with CaptureQueriesContext(connection) as large:
            client.get('/dashboard/get/')
        self.assertEqual(len(small), len(large))
        self.assertLessEqual(len(large), 30)

    def test_the_section_admin_screen(self) -> None:
        manager = self.staff('Dashboard Managers')
        client = Client()
        client.force_login(manager)
        url = '/admin/dashboard/dashboardsection/'
        self.assertEqual(client.get(url).status_code, 200)
        videos = DashboardSection.objects.get(key='videos')
        client.post(f'{url}{videos.pk}/change/', {'title': 'Watch', 'is_enabled': 'on', 'min_level': 'active', 'sort_order': '5', '_save': 'Save'}, follow=True)
        videos.refresh_from_db()
        self.assertEqual((videos.title, videos.min_level, videos.sort_order), ('Watch', 'active', 5))
        profile = DashboardSection.objects.get(key='profile')
        client.post(f'{url}{profile.pk}/change/', {'title': 'Profile', 'min_level': 'permanent', 'sort_order': '10', '_save': 'Save'}, follow=True)   # tries to switch it off and restrict it
        profile.refresh_from_db()
        self.assertEqual((profile.is_enabled, profile.min_level), (True, 'general'))
        self.assertEqual(client.get(url + 'add/').status_code, 403)
        self.assertEqual(client.get(f'{url}{videos.pk}/delete/').status_code, 403)

    def test_only_dashboard_managers_and_superusers_can_change_the_sections(self) -> None:
        url = '/admin/dashboard/dashboardsection/'
        videos = DashboardSection.objects.get(key='videos')
        for blocked in (self.staff(), self.staff('Content Publishers'), self.staff('Member Managers'), self.staff('Portal Managers')):
            client = Client()
            client.force_login(blocked)
            self.assertEqual(client.get(url).status_code, 403)
            client.post(f'{url}{videos.pk}/change/', {'title': 'Hacked', 'min_level': 'general', 'sort_order': '1', '_save': 'Save'})
        videos.refresh_from_db()
        self.assertEqual(videos.title, 'Videos')
        self.assertEqual(Client().get(url).status_code, 302)
        member_client = Client()
        member_client.force_login(self.member())
        self.assertEqual(member_client.get(url).status_code, 302)
        codes = set(Group.objects.get(name='Dashboard Managers').permissions.values_list('codename', flat=True))
        self.assertEqual(codes, {'view_dashboardsection', 'change_dashboardsection'})


class SwaggerTests(DashboardBase):
    def test_paths_in_schema(self) -> None:
        body = APIClient().get('/api/schema/').content.decode()
        for path in ('/dashboard/get/', '/notifications/get_all/', '/notifications/unread_count/', '/notifications/mark_read/'):
            self.assertIn(path, body)
