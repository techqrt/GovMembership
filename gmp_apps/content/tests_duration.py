import importlib
from unittest import mock

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from gmp.config import Configurations
from gmp_apps.content.models import ContentItem
from gmp_apps.content import tests as content_tests
from gmp_apps.content.tests import ContentApiBase


def words(count: int) -> str:
    return ' '.join(['word'] * count)


class ReadMinutesTests(ContentApiBase):
    def test_the_estimate_rounds_up_with_a_minimum_of_one(self) -> None:
        cases = {0: None, 1: 1, 199: 1, 200: 1, 201: 2, 400: 2, 401: 3, 1000: 5}
        for count, expected in cases.items():
            self.assertEqual(ContentItem.estimate_read_minutes(words(count)), expected, count)
        self.assertIsNone(ContentItem.estimate_read_minutes('   \n\t  '))
        self.assertEqual(ContentItem.estimate_read_minutes('line one\nline two\n\nline three'), 1)

    def test_it_is_stored_when_saved_and_updated_when_the_body_changes(self) -> None:
        item = self.item('Long one', body=words(450))
        self.assertEqual(ContentItem.objects.get(pk=item.pk).read_minutes, 3)
        item.body = words(10)
        item.save()
        self.assertEqual(ContentItem.objects.get(pk=item.pk).read_minutes, 1)
        item.body = ''
        item.save()
        self.assertIsNone(ContentItem.objects.get(pk=item.pk).read_minutes)

    def test_the_reading_speed_comes_from_the_configuration(self) -> None:
        with mock.patch.object(Configurations, 'content_read_words_per_minute', 100):
            item = self.item('Slow readers', body=words(250))
        self.assertEqual(ContentItem.objects.get(pk=item.pk).read_minutes, 3)

    def test_members_get_it_in_the_list_the_detail_and_the_dashboard(self) -> None:
        item = self.item('Readable', body=words(450))
        client = self.as_user(self.member())
        self.assertEqual(client.get('/content/get_all/').data['data']['data'][0]['readMinutes'], 3)
        self.assertEqual(client.get(f'/content/get/?content_id={item.content_id}').data['data']['readMinutes'], 3)
        sections = {s['key']: s for s in client.get('/dashboard/get/').data['data']['sections']}
        self.assertEqual(sections['posts']['data']['items'][0]['readMinutes'], 3)

    def test_an_item_without_a_body_has_no_read_time(self) -> None:
        self.item('Video only', body='', content_type='video', video_url='https://www.youtube.com/watch?v=abc123', summary='')
        self.assertIsNone(self.as_user(self.member()).get('/content/get_all/').data['data']['data'][0]['readMinutes'])

    def test_listing_never_loads_the_long_body(self) -> None:
        def count() -> int:
            with CaptureQueriesContext(connection) as queries:
                self.as_user(self.member()).get('/content/get_all/?limit=100')
            return len(queries)

        self.item('One', body=words(500))
        small = count()
        for index in range(6):
            self.item(f'More {index}', body=words(500))
        self.assertEqual(count(), small)

    def test_the_value_cannot_be_set_by_anyone(self) -> None:
        self.assertFalse(ContentItem._meta.get_field('read_minutes').editable)

    def test_old_rows_are_filled_in_by_the_migration(self) -> None:
        first, second = self.item('Old one', body=words(450)), self.item('Old empty', body='')
        ContentItem.objects.update(read_minutes=None)
        importlib.import_module('gmp_apps.content.migrations.0004_backfill_read_minutes').backfill(apps, None)
        self.assertEqual(ContentItem.objects.get(pk=first.pk).read_minutes, 3)
        self.assertIsNone(ContentItem.objects.get(pk=second.pk).read_minutes)


class DurationTests(ContentApiBase):
    VIDEO = {'content_type': 'video', 'video_url': 'https://www.youtube.com/watch?v=abc123'}

    def test_a_video_can_have_a_duration_and_members_see_it(self) -> None:
        item = self.item('Clip', duration_seconds=754, **self.VIDEO)
        client = self.as_user(self.member())
        self.assertEqual(client.get('/content/get_all/').data['data']['data'][0]['durationSeconds'], 754)
        self.assertEqual(client.get(f'/content/get/?content_id={item.content_id}').data['data']['durationSeconds'], 754)

    def test_it_is_optional_and_null_by_default(self) -> None:
        self.item('No length', **self.VIDEO)
        self.assertIsNone(self.as_user(self.member()).get('/content/get_all/').data['data']['data'][0]['durationSeconds'])

    def test_only_videos_can_have_one(self) -> None:
        for kind in ('post', 'announcement', 'tutorial', 'org_update'):
            item = ContentItem(title='x', body='b', category=self.general, content_type=kind, duration_seconds=60)
            with self.assertRaises(ValidationError, msg=kind):
                item.full_clean()

    def test_the_range_is_one_second_to_a_day(self) -> None:
        for bad in (0, -5, 86401):
            with self.assertRaises(ValidationError, msg=bad):
                ContentItem(title='x', category=self.general, summary='s', duration_seconds=bad, **self.VIDEO).full_clean()
        for good in (1, 86400):
            ContentItem(title='x', category=self.general, summary='s', duration_seconds=good, **self.VIDEO).full_clean()

    def test_the_schema_lists_the_new_fields(self) -> None:
        body = self.as_user(None).get('/api/schema/').content.decode()
        self.assertIn('durationSeconds', body)
        self.assertIn('readMinutes', body)


class AdminDurationTests(content_tests.ContentAdminTests):
    """Reuses the content admin fixtures (form, add, edit helpers)."""

    def test_editors_set_a_video_duration_in_the_admin(self) -> None:
        self.add(self.editor, content_type='video', video_url='https://www.youtube.com/watch?v=abc123', duration_seconds='754')
        item = ContentItem.objects.get()
        self.assertEqual((item.duration_seconds, item.status), (754, 'draft'))

    def test_a_duration_on_a_post_is_rejected_by_the_form(self) -> None:
        self.add(self.editor, content_type='post', duration_seconds='60')
        self.assertEqual(ContentItem.objects.count(), 0)

    def test_bad_durations_are_rejected_by_the_form(self) -> None:
        for bad in ('0', '86401', '-3', 'abc', '1.5'):
            self.add(self.editor, content_type='video', video_url='https://www.youtube.com/watch?v=abc123', duration_seconds=bad)
        self.assertEqual(ContentItem.objects.count(), 0)

    def test_saving_in_the_admin_computes_the_read_time(self) -> None:
        self.add(self.editor, body=words(450))
        self.assertEqual(ContentItem.objects.get().read_minutes, 3)


class VideoQualityTests(ContentApiBase):
    VIDEO = {'content_type': 'video', 'video_url': 'https://www.youtube.com/watch?v=abc123'}

    def test_members_see_the_chip_in_list_detail_and_dashboard(self) -> None:
        item = self.item('Clip', video_quality='4k', **self.VIDEO)
        client = self.as_user(self.member())
        row = client.get('/content/get_all/').data['data']['data'][0]
        self.assertEqual((row['videoQuality'], row['videoQualityLabel']), ('4k', '4K Ultra HD'))
        detail = client.get(f'/content/get/?content_id={item.content_id}').data['data']
        self.assertEqual((detail['videoQuality'], detail['videoQualityLabel']), ('4k', '4K Ultra HD'))
        sections = {s['key']: s for s in client.get('/dashboard/get/').data['data']['sections']}
        self.assertEqual(sections['videos']['data']['items'][0]['videoQualityLabel'], '4K Ultra HD')

    def test_every_choice_has_its_label(self) -> None:
        labels = {'sd': 'SD', 'hd': 'HD', 'full_hd': 'Full HD', '4k': '4K Ultra HD'}
        for key, label in labels.items():
            self.assertEqual(ContentItem(video_quality=key).get_video_quality_display(), label)

    def test_it_is_optional_and_null_when_not_set(self) -> None:
        self.item('Plain', **self.VIDEO)
        row = self.as_user(self.member()).get('/content/get_all/').data['data']['data'][0]
        self.assertEqual((row['videoQuality'], row['videoQualityLabel']), (None, None))

    def test_only_videos_can_have_one_and_only_known_values(self) -> None:
        for kind in ('post', 'announcement', 'tutorial', 'org_update'):
            with self.assertRaises(ValidationError, msg=kind):
                ContentItem(title='x', body='b', category=self.general, content_type=kind, video_quality='hd').full_clean()
        with self.assertRaises(ValidationError):
            ContentItem(title='x', category=self.general, summary='s', video_quality='8k', **self.VIDEO).full_clean()

    def test_the_schema_lists_the_fields(self) -> None:
        body = self.as_user(None).get('/api/schema/').content.decode()
        self.assertIn('videoQualityLabel', body)


class AdminVideoQualityTests(content_tests.ContentAdminTests):
    def test_editors_pick_the_quality_in_the_admin(self) -> None:
        self.add(self.editor, content_type='video', video_url='https://www.youtube.com/watch?v=abc123', video_quality='full_hd')
        self.assertEqual(ContentItem.objects.get().video_quality, 'full_hd')

    def test_a_quality_on_a_post_or_an_unknown_value_is_rejected(self) -> None:
        self.add(self.editor, content_type='post', video_quality='hd')
        self.add(self.editor, content_type='video', video_url='https://www.youtube.com/watch?v=abc123', video_quality='8k')
        self.assertEqual(ContentItem.objects.count(), 0)


for _name in [n for n in dir(content_tests.ContentAdminTests) if n.startswith('test_')]:
    if _name not in AdminVideoQualityTests.__dict__:
        setattr(AdminVideoQualityTests, _name, None)


# Do not run the parent's own tests a second time here.
for _name in [n for n in dir(content_tests.ContentAdminTests) if n.startswith('test_')]:
    if _name not in AdminDurationTests.__dict__:
        setattr(AdminDurationTests, _name, None)
