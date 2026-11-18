import atexit
import shutil
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db.models import ProtectedError
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from gmp.config import Configurations
from gmp_apps.authentication.models import User
from gmp_apps.content.models import ContentCategory, ContentItem
from gmp_apps.content.models.content_item import levels_visible_to
from gmp_apps.content.validators import validate_video_url

PASSWORD = 'Sunrise#Valley42'
FAST_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
MEDIA_TMP = tempfile.mkdtemp(prefix='gmp-test-content-')
atexit.register(shutil.rmtree, MEDIA_TMP, ignore_errors=True)
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 40
JPG = b'\xff\xd8\xff\xe0' + b'0' * 40
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
HTML_BYTES = b'<html><script>alert(1)</script></html>'
HOUR = timedelta(hours=1)


def clean_media() -> None:
    shutil.rmtree(Path(MEDIA_TMP) / 'content', ignore_errors=True)


class VideoUrlTests(TestCase):
    def test_allowed_hosts_over_https(self) -> None:
        for good in ('https://www.youtube.com/watch?v=abc', 'https://youtube.com/watch?v=abc', 'https://m.youtube.com/watch?v=abc',
                     'https://youtu.be/abc', 'https://vimeo.com/123', 'https://player.vimeo.com/video/123'):
            validate_video_url(good)

    def test_everything_else_is_refused(self) -> None:
        for bad in ('http://www.youtube.com/watch?v=abc', 'https://example.com/video.mp4', 'https://youtube.com.evil.example/x',
                    'https://evilyoutube.com/x', 'https://notyoutu.be/x', 'javascript:alert(1)', 'https://user:pw@youtube.com/x',
                    'https://youtube.com/a b', 'ftp://youtube.com/x', 'https://127.0.0.1/x', 'https://youtube/x', ''):
            with self.assertRaises(ValidationError, msg=bad):
                validate_video_url(bad)

    def test_allowed_hosts_are_configurable(self) -> None:
        with mock.patch.object(Configurations, 'content_video_hosts', ['video.gov.in']):
            validate_video_url('https://video.gov.in/watch/1')
            validate_video_url('https://cdn.video.gov.in/watch/1')
            with self.assertRaises(ValidationError):
                validate_video_url('https://www.youtube.com/watch?v=abc')


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class ContentModelTests(TestCase):
    def setUp(self) -> None:
        clean_media()
        self.addCleanup(clean_media)
        self.general = ContentCategory.objects.get(name='General')

    def item(self, **extra) -> ContentItem:
        defaults = {'title': 'T', 'body': 'text', 'category': self.general}
        defaults.update(extra)
        return ContentItem.objects.create(**defaults)

    def test_seeded_category(self) -> None:
        self.assertEqual(list(ContentCategory.objects.values_list('name', flat=True)), ['General'])

    def test_level_mapping(self) -> None:
        self.assertEqual(levels_visible_to('general'), ['general'])
        self.assertEqual(levels_visible_to('active'), ['general', 'active'])
        self.assertEqual(levels_visible_to('permanent'), ['general', 'active', 'permanent'])
        self.assertEqual(levels_visible_to('nonsense'), ['general'])  # unknown means the lowest level

    def test_publishing_without_a_time_means_now_and_drafts_stay_unscheduled(self) -> None:
        published = self.item(status='published')
        self.assertLessEqual(abs(timezone.now() - published.publish_at), timedelta(seconds=5))
        self.assertIsNone(self.item(status='draft').publish_at)
        future = timezone.now() + 5 * HOUR
        self.assertEqual(self.item(status='published', publish_at=future).publish_at, future)

    def test_states(self) -> None:
        now = timezone.now()
        self.assertEqual(self.item(status='draft').state(), 'draft')
        self.assertEqual(self.item(status='archived').state(), 'archived')
        self.assertEqual(self.item(status='published', publish_at=now + HOUR).state(), 'scheduled')
        self.assertEqual(self.item(status='published', publish_at=now - 2 * HOUR, expire_at=now - HOUR).state(), 'expired')
        self.assertEqual(self.item(status='published', publish_at=now - HOUR, expire_at=now + HOUR).state(), 'live')

    def test_clean_rules(self) -> None:
        now = timezone.now()
        cases = [
            self.item(content_type='video', video_url=''),
            self.item(publish_at=now, expire_at=now - HOUR),
            self.item(publish_at=now, expire_at=now),
            self.item(status='published', body='', summary='', video_url=''),
        ]
        for case in cases:
            with self.assertRaises(ValidationError):
                case.full_clean()
        self.item(content_type='video', video_url='https://youtu.be/abc').full_clean()
        self.item(status='published', summary='only a summary').full_clean()

    def test_live_and_visible_for(self) -> None:
        now = timezone.now()
        visible = self.item(title='ok', status='published', publish_at=now - HOUR)
        self.item(title='draft')
        self.item(title='future', status='published', publish_at=now + HOUR)
        self.item(title='expired', status='published', publish_at=now - 2 * HOUR, expire_at=now - HOUR)
        self.item(title='archived', status='archived', publish_at=now - HOUR)
        self.item(title='active only', status='published', publish_at=now - HOUR, min_level='active')
        self.item(title='hidden cat', status='published', publish_at=now - HOUR, category=ContentCategory.objects.create(name='Off', is_active=False))
        self.assertEqual([i.title for i in ContentItem.visible_for('general').order_by('title')], ['ok'])
        self.assertEqual(sorted(i.title for i in ContentItem.visible_for('active')), ['active only', 'ok'])
        self.assertEqual(ContentItem.live().count(), 2)
        self.assertIn(visible, ContentItem.live())

    def test_cover_is_named_after_its_content_and_replaced_files_are_removed(self) -> None:
        item = self.item()
        item.cover_image = ContentFile(PNG, name='holiday.html')
        item.save()
        first = Path(django_settings.MEDIA_ROOT) / item.cover_image.name
        self.assertRegex(item.cover_image.name, r'^content/[0-9a-f]{24}\.png$')
        self.assertTrue(first.is_file())
        item.cover_image = ContentFile(JPG, name='x')
        item.save()
        self.assertFalse(first.exists())
        self.assertTrue((Path(django_settings.MEDIA_ROOT) / item.cover_image.name).is_file())
        last = Path(django_settings.MEDIA_ROOT) / item.cover_image.name
        item.delete()
        self.assertFalse(last.exists())

    def test_a_cover_that_is_not_an_image_is_refused(self) -> None:
        for bad in (HTML_BYTES, SVG, b'', b'not an image'):
            item = self.item()
            item.cover_image = ContentFile(bad, name='x.png')
            with self.assertRaises(ValidationError):
                item.save()

    def test_a_category_with_content_cannot_be_deleted(self) -> None:
        self.item()
        with self.assertRaises(ProtectedError):
            self.general.delete()


@override_settings(PASSWORD_HASHERS=FAST_HASHERS, MEDIA_ROOT=MEDIA_TMP)
class ContentApiBase(APITestCase):
    def setUp(self) -> None:
        clean_media()
        self.addCleanup(clean_media)
        cache.clear()
        call_command('setup_admin_groups', stdout=StringIO())
        self.counter = 0
        self.general = ContentCategory.objects.get(name='General')

    def member(self, level: str = 'general') -> User:
        self.counter += 1
        return User.objects.create_user(full_name=f'Member {self.counter}', password=PASSWORD, email=f'm{self.counter}@example.com',
                                        email_verified=True, membership_level=level)

    def staff(self, *groups: str, role: str = 'admin') -> User:
        self.counter += 1
        user = User.objects.create_user(full_name='Staff', password=PASSWORD, email=f'st{self.counter}@example.com', is_staff=True,
                                        role=role, email_verified=True)
        user.groups.add(*Group.objects.filter(name__in=groups))
        return user

    @staticmethod
    def as_user(user: User | None) -> APIClient:
        client = APIClient()
        if user:
            client.force_authenticate(user)
        return client

    def item(self, title: str = 'Item', **extra) -> ContentItem:
        defaults = {'body': f'Body of {title}', 'summary': f'About {title}', 'category': self.general, 'status': 'published',
                    'publish_at': timezone.now() - HOUR}
        defaults.update(extra)
        return ContentItem.objects.create(title=title, **defaults)

    def titles(self, user: User, query: str = '') -> list[str]:
        rows = self.as_user(user).get(f'/content/get_all/?limit=100&{query}').data['data']['data']
        return [r['title'] for r in rows]


class LevelRestrictionTests(ContentApiBase):
    def seed(self) -> dict[str, ContentItem]:
        return {level: self.item(f'For {level}', min_level=level) for level in ('general', 'active', 'permanent')}

    def test_each_level_sees_exactly_its_own_and_lower_content(self) -> None:
        self.seed()
        self.assertEqual(sorted(self.titles(self.member('general'))), ['For general'])
        self.assertEqual(sorted(self.titles(self.member('active'))), ['For active', 'For general'])
        self.assertEqual(sorted(self.titles(self.member('permanent'))), ['For active', 'For general', 'For permanent'])

    def test_restricted_content_is_a_404_not_a_403(self) -> None:
        items = self.seed()
        general = self.as_user(self.member('general'))
        self.assertEqual(general.get(f'/content/get/?content_id={items["general"].content_id}').status_code, 200)
        for level in ('active', 'permanent'):
            response = general.get(f'/content/get/?content_id={items[level].content_id}')
            self.assertEqual(response.status_code, 404)
            self.assertNotIn(f'For {level}', str(response.data))
        self.assertEqual(general.get('/content/get/?content_id=999999').data, general.get(f'/content/get/?content_id={items["permanent"].content_id}').data)

    def test_restricted_content_cannot_be_discovered_by_search_filter_sort_values_or_counts(self) -> None:
        secret = self.item('Secret permanent plan', min_level='permanent', summary='confidential', body='classified wording')
        member = self.member('general')
        client = self.as_user(member)
        for query in ('search_key=Secret', 'search_key=classified', 'search_key=confidential', f'filter_key=categoryId&filter_value={self.general.category_id}',
                      'filter_key=type&filter_value=post', 'sort_by=title&sort_order=asc', 'values=contentId,title'):
            rows = client.get(f'/content/get_all/?{query}').data['data']['data']
            self.assertNotIn(secret.content_id, [r['contentId'] for r in rows], query)
        self.assertEqual(client.get('/content/category/get_all/').data['data']['data'], [])
        self.assertEqual(client.get('/content/get_all/?search_key=permanent').data['data']['data'], [])

    def test_search_cannot_reach_internal_columns(self) -> None:
        self.item('Plain one', min_level='general')
        client = self.as_user(self.member('permanent'))
        for needle in ('published', 'draft', 'min_level', 'permanent', 'archived'):   # internal values; 'general' is a category name, which is searchable on purpose
            hits = [r['title'] for r in client.get(f'/content/get_all/?search_key={needle}').data['data']['data']]
            self.assertEqual(hits, [], needle)

    def test_a_promotion_or_demotion_changes_access_immediately(self) -> None:
        item = self.item('Active only', min_level='active')
        member = self.member('general')
        client = self.as_user(member)
        self.assertEqual(client.get(f'/content/get/?content_id={item.content_id}').status_code, 404)
        User.objects.filter(pk=member.pk).update(membership_level='active')
        self.assertEqual(client.get(f'/content/get/?content_id={item.content_id}').status_code, 200)
        User.objects.filter(pk=member.pk).update(membership_level='general')
        self.assertEqual(client.get(f'/content/get/?content_id={item.content_id}').status_code, 404)

    def test_category_counts_only_count_what_the_member_can_read(self) -> None:
        other = ContentCategory.objects.create(name='Members only', sort_order=1)
        self.item('A')
        self.item('B', min_level='active')
        self.item('C', min_level='permanent', category=other)
        general = self.as_user(self.member('general')).get('/content/category/get_all/').data['data']['data']
        permanent = self.as_user(self.member('permanent')).get('/content/category/get_all/').data['data']['data']
        self.assertEqual(general, [{'categoryId': self.general.category_id, 'name': 'General', 'itemCount': 1}])
        self.assertEqual(permanent, [{'categoryId': self.general.category_id, 'name': 'General', 'itemCount': 2},
                                     {'categoryId': other.category_id, 'name': 'Members only', 'itemCount': 1}])


class ScheduleAndStateTests(ContentApiBase):
    def test_only_live_content_is_visible(self) -> None:
        now = timezone.now()
        self.item('Live now')
        self.item('Live until later', expire_at=now + HOUR)
        self.item('Still a draft', status='draft', publish_at=None)
        self.item('Archived', status='archived')
        self.item('Scheduled', publish_at=now + HOUR)
        self.item('Expired', publish_at=now - 2 * HOUR, expire_at=now - HOUR)
        self.assertEqual(sorted(self.titles(self.member())), ['Live now', 'Live until later'])

    def test_content_appears_when_its_time_comes_and_disappears_when_it_expires(self) -> None:
        item = self.item('Timed', publish_at=timezone.now() + HOUR)
        member = self.member()
        url = f'/content/get/?content_id={item.content_id}'
        self.assertEqual(self.as_user(member).get(url).status_code, 404)
        ContentItem.objects.filter(pk=item.pk).update(publish_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.as_user(member).get(url).status_code, 200)
        ContentItem.objects.filter(pk=item.pk).update(expire_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.as_user(member).get(url).status_code, 404)

    def test_unpublished_or_archived_after_the_fact_disappears(self) -> None:
        item = self.item('Withdrawn')
        member = self.member()
        url = f'/content/get/?content_id={item.content_id}'
        self.assertEqual(self.as_user(member).get(url).status_code, 200)
        for status in ('draft', 'archived'):
            ContentItem.objects.filter(pk=item.pk).update(status=status)
            self.assertEqual(self.as_user(member).get(url).status_code, 404, status)

    def test_an_inactive_category_hides_its_content_everywhere(self) -> None:
        hidden = ContentCategory.objects.create(name='Switched off', is_active=False)
        item = self.item('Inside', category=hidden)
        member = self.as_user(self.member())
        self.assertEqual(member.get('/content/get_all/').data['data']['data'], [])
        self.assertEqual(member.get(f'/content/get/?content_id={item.content_id}').status_code, 404)
        self.assertEqual(member.get('/content/category/get_all/').data['data']['data'], [])


class MemberContentApiTests(ContentApiBase):
    def test_row_and_detail_shapes_expose_nothing_internal(self) -> None:
        item = self.item('Shape', min_level='general', is_pinned=True, expire_at=timezone.now() + 5 * HOUR)
        client = self.as_user(self.member())
        listing = client.get('/content/get_all/')
        detail = client.get(f'/content/get/?content_id={item.content_id}')
        row = listing.data['data']['data'][0]
        self.assertEqual(set(row), {'contentId', 'type', 'title', 'summary', 'categoryId', 'categoryName', 'coverImageUrl', 'videoUrl', 'isPinned', 'publishedDateTime'})
        self.assertEqual(set(detail.data['data']), set(row) | {'body'})
        self.assertNotIn('body', row)
        self.assertEqual((detail.data['data']['body'], row['isPinned']), ('Body of Shape', True))
        for response in (listing, detail):
            text = str(response.data['data'])
            for internal in ('status', 'minLevel', 'min_level', 'expireAt', 'expire_at', 'createdBy', 'created_by', 'draft'):
                self.assertNotIn(internal, text)

    def test_cover_image_is_an_absolute_url_on_our_server(self) -> None:
        item = self.item('Pictured')
        item.cover_image = ContentFile(PNG, name='x.png')
        item.save()
        client = self.as_user(self.member())
        url = client.get('/content/get_all/').data['data']['data'][0]['coverImageUrl']
        self.assertEqual(url, f'http://testserver{item.cover_image.url}')
        with mock.patch.object(Configurations, 'media_base_url', 'https://cdn.example.com/'):
            self.assertTrue(client.get(f'/content/get/?content_id={item.content_id}').data['data']['coverImageUrl'].startswith('https://cdn.example.com/media/content/'))
        plain = self.item('No cover')
        self.assertIsNone(self.as_user(self.member()).get(f'/content/get/?content_id={plain.content_id}').data['data']['coverImageUrl'])

    def test_videos_are_links_to_the_video_host(self) -> None:
        video = self.item('How to apply', content_type='video', video_url='https://youtu.be/abc123')
        client = self.as_user(self.member())
        self.assertEqual(client.get(f'/content/get/?content_id={video.content_id}').data['data']['videoUrl'], 'https://youtu.be/abc123')
        self.assertEqual([r['title'] for r in client.get('/content/get_all/?filter_key=type&filter_value=video').data['data']['data']], ['How to apply'])

    def test_order_pagination_filters_search_sort_values(self) -> None:
        now = timezone.now()
        other = ContentCategory.objects.create(name='Tutorials', sort_order=2)
        self.item('Old post', publish_at=now - 5 * HOUR)
        self.item('New post', publish_at=now - HOUR)
        self.item('Pinned old', publish_at=now - 9 * HOUR, is_pinned=True)
        self.item('Guide', content_type='tutorial', category=other, publish_at=now - 3 * HOUR, summary='step by step')
        client = self.as_user(self.member())
        self.assertEqual(self.titles(self.member()), ['Pinned old', 'New post', 'Guide', 'Old post'])
        page = client.get('/content/get_all/?limit=3').data['data']
        self.assertEqual((len(page['data']), page['totalPage']), (3, 2))
        self.assertIn('nextPageUrl', page)
        self.assertEqual(self.titles(self.member(), f'filter_key=categoryId&filter_value={other.category_id}'), ['Guide'])
        self.assertEqual(self.titles(self.member(), 'filter_key=type&filter_value=tutorial'), ['Guide'])
        self.assertEqual(self.titles(self.member(), 'search_key=step'), ['Guide'])
        self.assertEqual(self.titles(self.member(), 'search_key=Tutorials'), ['Guide'])
        self.assertEqual(self.titles(self.member(), 'sort_by=title&sort_order=asc'), ['Guide', 'New post', 'Old post', 'Pinned old'])
        self.assertEqual(set(client.get('/content/get_all/?values=contentId,title').data['data']['data'][0]), {'contentId', 'title'})
        self.assertEqual(len(client.get('/content/get_all/?from_date=01-01-20').data['data']['data']), 4)
        for bad in ('sort_by=status', 'sort_by=minLevel', 'filter_key=status&filter_value=draft', 'filter_key=minLevel&filter_value=permanent', 'page_num=9'):
            self.assertEqual(client.get(f'/content/get_all/?{bad}').status_code, 400, bad)

    def test_get_validation(self) -> None:
        client = self.as_user(self.member())
        self.assertEqual(client.get('/content/get/').status_code, 400)
        self.assertEqual(client.get('/content/get/?content_id=abc').status_code, 400)
        self.assertEqual(client.get('/content/get/?content_id=999999').status_code, 404)

    def test_authentication_and_roles_on_every_endpoint(self) -> None:
        item = self.item('Any')
        for path in ('/content/get_all/', f'/content/get/?content_id={item.content_id}', '/content/category/get_all/'):
            self.assertEqual(self.as_user(None).get(path).status_code, 401, path)
            self.assertEqual(self.as_user(self.staff('Content Publishers')).get(path).status_code, 403, path)
            self.assertEqual(self.as_user(self.member()).get(path).status_code, 200, path)

    def test_a_suspended_member_loses_access(self) -> None:
        member = self.member()
        self.item('Any')
        login = APIClient().post('/auth/login/', {'identifier': member.email, 'password': PASSWORD}, format='json')
        token = login.data['data']['access']
        self.assertEqual(APIClient().get('/content/get_all/', HTTP_AUTHORIZATION=f'Bearer {token}').status_code, 200)
        User.objects.filter(pk=member.pk).update(is_active=False)
        self.assertEqual(APIClient().get('/content/get_all/', HTTP_AUTHORIZATION=f'Bearer {token}').status_code, 401)

    def test_query_counts_are_fixed(self) -> None:
        for index in range(6):
            item = self.item(f'Item {index}')
            item.cover_image = ContentFile(PNG + str(index).encode(), name='x.png')
            item.save()
        client = self.as_user(self.member())
        with self.assertNumQueries(3):  # member level, count, one page (category joined)
            client.get('/content/get_all/')
        first_id = ContentItem.objects.first().content_id
        with self.assertNumQueries(2):  # member level, the item
            client.get(f'/content/get/?content_id={first_id}')
        with self.assertNumQueries(3):  # member level, counts, categories
            client.get('/content/category/get_all/')

    def test_there_is_no_way_to_write_react_comment_or_count_views(self) -> None:
        client = self.as_user(self.member())
        for method in ('post', 'put', 'patch', 'delete'):
            self.assertEqual(getattr(client, method)('/content/get_all/', {}, format='json').status_code, 405, method)
        schema = APIClient().get('/api/schema/').content.decode()
        for path in ('/content/get_all/', '/content/get/', '/content/category/get_all/'):
            self.assertIn(path, schema)
        for forbidden in ('/content/create', '/content/like', '/content/comment', '/content/view'):
            self.assertNotIn(forbidden, schema)


@override_settings(PASSWORD_HASHERS=FAST_HASHERS, MEDIA_ROOT=MEDIA_TMP)
class ContentAdminTests(ContentApiBase):
    LIST = '/admin/content/contentitem/'
    CATS = '/admin/content/contentcategory/'

    def setUp(self) -> None:
        super().setUp()
        self.editor = self.staff('Content Editors')
        self.publisher = self.staff('Content Publishers')

    @staticmethod
    def client_for(user: User | None) -> Client:
        client = Client()
        if user:
            client.force_login(user)
        return client

    def form(self, **overrides) -> dict:
        data = {'content_type': 'post', 'title': 'Hello', 'summary': 'sum', 'body': 'Body text', 'category': self.general.pk,
                'video_url': '', 'min_level': 'general', 'status': 'draft', '_save': 'Save'}
        data.update(overrides)
        return {k: v for k, v in data.items() if v != ''}

    def add(self, user: User, **overrides):
        return self.client_for(user).post(self.LIST + 'add/', self.form(**overrides), follow=True)

    def edit(self, user: User, item: ContentItem, **overrides):
        base = self.form(title=item.title, body=item.body, summary=item.summary, status=item.status)
        base.update(overrides)
        return self.client_for(user).post(f'{self.LIST}{item.pk}/change/', base, follow=True)

    def test_editor_creates_drafts_only_and_the_author_is_recorded(self) -> None:
        self.add(self.editor, status='published')   # tries to publish
        item = ContentItem.objects.get()
        self.assertEqual((item.status, item.publish_at, item.created_by_id), ('draft', None, self.editor.user_id))
        self.assertEqual(ContentItem.visible_for('permanent').count(), 0)

    def test_editor_cannot_publish_through_the_form_or_the_actions(self) -> None:
        item = self.item('Draft', status='draft', publish_at=None)
        self.edit(self.editor, item, status='published')
        for action in ('publish_selected', 'unpublish_selected', 'archive_selected'):
            self.client_for(self.editor).post(self.LIST, {'action': action, '_selected_action': [item.pk]}, follow=True)
        item.refresh_from_db()
        self.assertEqual(item.status, 'draft')

    def test_editor_can_fix_the_text_of_published_content_but_not_change_its_status_or_delete_it(self) -> None:
        item = self.item('Live')
        self.edit(self.editor, item, title='Live (typo fixed)', status='archived')
        item.refresh_from_db()
        self.assertEqual((item.title, item.status), ('Live (typo fixed)', 'published'))
        self.client_for(self.editor).post(f'{self.LIST}{item.pk}/delete/', {'post': 'yes'}, follow=True)
        self.assertTrue(ContentItem.objects.filter(pk=item.pk).exists())
        self.assertEqual(self.client_for(self.editor).get(f'{self.LIST}{item.pk}/delete/').status_code, 403)

    def test_publisher_publishes_unpublishes_archives_and_deletes(self) -> None:
        item = self.item('Draft', status='draft', publish_at=None)
        member = self.as_user(self.member())
        client = self.client_for(self.publisher)
        client.post(self.LIST, {'action': 'publish_selected', '_selected_action': [item.pk]}, follow=True)
        item.refresh_from_db()
        self.assertEqual((item.status, item.state()), ('published', 'live'))
        self.assertEqual(len(member.get('/content/get_all/').data['data']['data']), 1)
        client.post(self.LIST, {'action': 'unpublish_selected', '_selected_action': [item.pk]}, follow=True)
        self.assertEqual(member.get('/content/get_all/').data['data']['data'], [])
        client.post(self.LIST, {'action': 'archive_selected', '_selected_action': [item.pk]}, follow=True)
        item.refresh_from_db()
        self.assertEqual(item.status, 'archived')
        client.post(f'{self.LIST}{item.pk}/delete/', {'post': 'yes'}, follow=True)
        self.assertFalse(ContentItem.objects.exists())

    def test_publish_skips_empty_items(self) -> None:
        empty = ContentItem.objects.create(title='Empty', category=self.general)
        response = self.client_for(self.publisher).post(self.LIST, {'action': 'publish_selected', '_selected_action': [empty.pk]}, follow=True)
        empty.refresh_from_db()
        self.assertEqual(empty.status, 'draft')
        self.assertContains(response, '1 had no body, summary or video')

    def test_scheduling_through_the_form(self) -> None:
        when = timezone.localtime(timezone.now() + 3 * HOUR)
        self.add(self.publisher, status='published', publish_at_0=when.strftime('%Y-%m-%d'), publish_at_1=when.strftime('%H:%M:%S'))
        item = ContentItem.objects.get()
        self.assertEqual(item.state(), 'scheduled')
        self.assertEqual(self.titles(self.member()), [])
        ContentItem.objects.filter(pk=item.pk).update(publish_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.titles(self.member()), ['Hello'])

    def test_invalid_input_is_rejected_and_nothing_is_saved(self) -> None:
        now = timezone.localtime(timezone.now())
        later, earlier = (now + 3 * HOUR), (now + HOUR)
        bad = (
            {'content_type': 'video', 'video_url': ''}, {'content_type': 'video', 'video_url': 'https://example.com/v.mp4'},
            {'video_url': 'http://www.youtube.com/watch?v=abc'}, {'video_url': 'javascript:alert(1)'},
            {'publish_at_0': later.strftime('%Y-%m-%d'), 'publish_at_1': later.strftime('%H:%M:%S'),
             'expire_at_0': earlier.strftime('%Y-%m-%d'), 'expire_at_1': earlier.strftime('%H:%M:%S')},
            {'status': 'published', 'body': '', 'summary': ''}, {'min_level': 'platinum'}, {'content_type': 'meme'},
        )
        for overrides in bad:
            self.add(self.publisher, **overrides)
        self.assertEqual(ContentItem.objects.count(), 0)

    def test_valid_video_is_saved(self) -> None:
        self.add(self.publisher, content_type='video', video_url='https://www.youtube.com/watch?v=abc', body='')
        self.assertEqual(ContentItem.objects.get().video_url, 'https://www.youtube.com/watch?v=abc')

    def test_cover_upload_is_checked_and_stored_by_content(self) -> None:
        self.add(self.editor, title='With cover', cover_image=SimpleUploadedFile('photo.html', PNG + b'ok'))
        item = ContentItem.objects.get()
        self.assertRegex(item.cover_image.name, r'^content/[0-9a-f]{24}\.png$')
        for name, content in (('a.png', HTML_BYTES), ('b.png', SVG), ('c.jpg', b''), ('d.png', b'not an image')):
            self.add(self.editor, title=f'Bad {name}', cover_image=SimpleUploadedFile(name, content))
        with mock.patch.object(Configurations, 'content_image_max_bytes', 50):
            self.add(self.editor, title='Too big', cover_image=SimpleUploadedFile('big.png', PNG + b'x' * 100))
        self.assertEqual(list(ContentItem.objects.values_list('title', flat=True)), ['With cover'])

    def test_minimum_level_is_set_in_the_admin_and_enforced_for_members(self) -> None:
        self.add(self.publisher, title='For Active', min_level='active', status='published')
        self.assertEqual(self.titles(self.member('general')), [])
        self.assertEqual(self.titles(self.member('active')), ['For Active'])

    def test_list_search_filters_and_state_column(self) -> None:
        now = timezone.now()
        self.item('Live one')
        self.item('Future one', publish_at=now + HOUR)
        self.item('Gone one', publish_at=now - 2 * HOUR, expire_at=now - HOUR)
        self.item('Draft one', status='draft', publish_at=None)
        client = self.client_for(self.editor)

        def found(query: str) -> list[str]:
            return sorted(i.title for i in client.get(f'{self.LIST}?{query}').context['cl'].result_list)

        self.assertEqual(found('visibility=live'), ['Live one'])
        self.assertEqual(found('visibility=scheduled'), ['Future one'])
        self.assertEqual(found('visibility=expired'), ['Gone one'])
        self.assertEqual(found('status__exact=draft'), ['Draft one'])
        self.assertEqual(found('q=Future'), ['Future one'])
        body = client.get(self.LIST).content.decode()
        for state in ('live', 'scheduled', 'expired', 'draft'):
            self.assertIn(f'>{state}<', body)

    def test_categories_deactivate_hides_content_and_delete_is_protected(self) -> None:
        item = self.item('In general')
        member = self.as_user(self.member())
        self.client_for(self.editor).post(f'{self.CATS}{self.general.pk}/change/', {'name': 'General', 'sort_order': '0', '_save': 'Save'}, follow=True)
        self.general.refresh_from_db()
        self.assertFalse(self.general.is_active)
        self.assertEqual(member.get('/content/get_all/').data['data']['data'], [])
        self.client_for(self.publisher).post(f'{self.CATS}{self.general.pk}/delete/', {'post': 'yes'}, follow=True)
        self.assertTrue(ContentCategory.objects.filter(pk=self.general.pk).exists())
        self.assertTrue(ContentItem.objects.filter(pk=item.pk).exists())

    def test_only_content_staff_can_use_the_content_admin(self) -> None:
        for blocked in (self.staff(), self.staff('Support Handlers'), self.staff('Portal Managers'), self.staff('Scheme Reviewers'), self.staff('Member Managers')):
            client = self.client_for(blocked)
            self.assertEqual(client.get(self.LIST).status_code, 403)
            client.post(self.LIST + 'add/', self.form(title='Sneaky'))
        self.assertEqual(ContentItem.objects.count(), 0)
        self.assertEqual(Client().get(self.LIST).status_code, 302)
        self.assertEqual(self.client_for(self.member()).get(self.LIST).status_code, 302)
        root = User.objects.create_superuser(full_name='Root', password=PASSWORD, email='root@example.com')
        self.assertEqual(self.client_for(root).get(self.LIST).status_code, 200)

    def test_content_staff_see_nothing_else(self) -> None:
        for staff in (self.editor, self.publisher):
            client = self.client_for(staff)
            for path in ('/admin/authentication/user/', '/admin/membership/referral/', '/admin/schemes/scheme/', '/admin/portals/complaintportal/'):
                self.assertEqual(client.get(path).status_code, 403, path)

    def test_group_permissions_are_exact(self) -> None:
        def codes(name: str) -> set[str]:
            return set(Group.objects.get(name=name).permissions.values_list('codename', flat=True))

        self.assertEqual(codes('Content Editors'), {'view_contentitem', 'add_contentitem', 'change_contentitem',
                                                    'view_contentcategory', 'add_contentcategory', 'change_contentcategory'})
        self.assertEqual(codes('Content Publishers'), codes('Content Editors') | {'delete_contentitem', 'publish_contentitem', 'delete_contentcategory'})

    def test_dashboard_cards_follow_permission(self) -> None:
        self.item('Live')
        self.item('Draft', status='draft', publish_at=None)

        def cards(user: User) -> dict[str, int]:
            return {c['title']: c['value'] for c in self.client_for(user).get('/admin/').context['dashboard_cards']}

        self.assertEqual(cards(self.editor), {'Content drafts': 1, 'Live content': 1, 'Scheduled content': 0})
        self.assertNotIn('Live content', cards(self.staff('Portal Managers')))


class SwaggerTests(ContentApiBase):
    def test_paths_in_schema(self) -> None:
        body = APIClient().get('/api/schema/').content.decode()
        for path in ('get_all', 'get', 'category/get_all'):
            self.assertIn(f'/content/{path}/', body)
