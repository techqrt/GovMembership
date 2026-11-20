from io import StringIO

from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from gmp_apps.app_text.models import AppText
from gmp_apps.authentication.models import User

GET_ALL = '/app_text/get_all/'
PASSWORD = 'Sunrise#Valley42'


class AppTextBase(TestCase):
    def setUp(self) -> None:
        cache.clear()
        call_command('setup_admin_groups', stdout=StringIO())

    def text(self, key: str, en: str = 'Home', hi: str = '', **extra) -> AppText:
        return AppText.objects.create(key=key, text_en=en, text_hi=hi, **extra)

    def staff(self, *groups: str) -> User:
        user = User.objects.create_user(full_name='Editor', password=PASSWORD, email=f'e{User.objects.count()}@example.com', is_staff=True, role='admin', email_verified=True)
        user.groups.add(*Group.objects.filter(name__in=groups))
        return user

    @staticmethod
    def get(**query):
        return APIClient().get(GET_ALL, query)


class AppTextApiTests(AppTextBase):
    def test_english_and_hindi_strings_with_a_per_string_english_fallback(self) -> None:
        self.text('home.title', 'Home', 'होम')
        self.text('home.help', 'Help')                      # no Hindi yet
        english = self.get(language='en').data['data']
        hindi = self.get(language='hi').data['data']
        self.assertEqual((english['language'], english['strings']), ('en', {'home.title': 'Home', 'home.help': 'Help'}))
        self.assertEqual((hindi['language'], hindi['strings']), ('hi', {'home.title': 'होम', 'home.help': 'Help'}))

    def test_the_default_language_is_english_and_it_is_public(self) -> None:
        self.text('home.title', 'Home', 'होम')
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['strings'], {'home.title': 'Home'})
        self.assertTrue(response.data['status'])

    def test_unsupported_languages_are_rejected(self) -> None:
        for bad in ('fr', 'HI', '', 'hi,en', '<script>'):
            self.assertEqual(self.get(language=bad).status_code, 400, bad)

    def test_inactive_strings_are_not_served(self) -> None:
        self.text('home.title', 'Home', 'होम')
        self.text('old.thing', 'Old', 'पुराना', is_active=False)
        self.assertEqual(set(self.get(language='hi').data['data']['strings']), {'home.title'})

    def test_last_updated_is_the_newest_change_and_null_when_empty(self) -> None:
        self.assertEqual(self.get().data['data'], {'language': 'en', 'lastUpdated': None, 'strings': {}})
        first = self.text('a.one', 'One')
        second = self.text('a.two', 'Two')
        AppText.objects.filter(pk=first.pk).update(updated_date_time='2020-01-01T00:00:00Z')
        second.refresh_from_db()
        self.assertEqual(self.get().data['data']['lastUpdated'], second.updated_date_time)

    def test_only_reads_are_allowed(self) -> None:
        for method in ('post', 'put', 'patch', 'delete'):
            self.assertEqual(getattr(APIClient(), method)(GET_ALL, {}, format='json').status_code, 405, method)

    def test_it_exposes_nothing_but_the_strings(self) -> None:
        self.text('home.title', 'Home', 'होम')
        data = self.get(language='hi').data['data']
        self.assertEqual(set(data), {'language', 'lastUpdated', 'strings'})

    def test_the_query_count_does_not_grow_with_the_number_of_strings(self) -> None:
        def count() -> int:
            with CaptureQueriesContext(connection) as queries:
                self.get(language='hi')
            return len(queries)

        self.text('k.one', 'One', 'एक')
        small = count()
        for index in range(20):
            self.text(f'k.more{index}', 'More', 'और')
        self.assertEqual(count(), small)

    def test_the_endpoint_is_throttled_per_ip(self) -> None:
        from unittest import mock

        from rest_framework.throttling import SimpleRateThrottle

        with mock.patch.object(SimpleRateThrottle, 'THROTTLE_RATES', {'app_text': '2/hour', 'auth': '100/hour'}):
            codes = [APIClient().get(GET_ALL).status_code for _ in range(4)]
        self.assertEqual(codes, [200, 200, 429, 429])

    def test_swagger_documents_it_as_public(self) -> None:
        schema = APIClient().get('/api/schema/?format=json').json()
        operation = schema['paths'][GET_ALL]['get']
        self.assertIn('language', [p['name'] for p in operation['parameters']])
        self.assertNotIn('401', operation['responses'])   # public: no login needed
        self.assertIn('AppTextResponseGetAll', str(operation['responses']['200']))


class AppTextModelTests(AppTextBase):
    def test_key_rules(self) -> None:
        for bad in ('', 'A', 'Home.title', '1home', 'home title', 'home-title', 'x', 'a' * 101, 'home.ti<tle'):
            with self.assertRaises(ValidationError, msg=bad):
                AppText(key=bad, text_en='x').full_clean()
        for good in ('home.title', 'ab', 'login_button', 'a1.b2.c3'):
            AppText(key=good, text_en='x').full_clean()

    def test_keys_are_unique_and_english_is_required(self) -> None:
        self.text('home.title')
        with self.assertRaises(ValidationError):
            AppText(key='home.title', text_en='x').full_clean()
        with self.assertRaises(ValidationError):
            AppText(key='other.key', text_en='').full_clean()

    def test_text_length_is_capped(self) -> None:
        with self.assertRaises(ValidationError):
            AppText(key='long.one', text_en='x' * 1001).full_clean()
        with self.assertRaises(ValidationError):
            AppText(key='long.two', text_en='x', text_hi='य' * 1001).full_clean()


class AppTextAdminTests(AppTextBase):
    LIST = '/admin/app_text/apptext/'

    def client_for(self, user: User) -> Client:
        client = Client()
        client.force_login(user)
        return client

    def test_the_group_has_exactly_the_text_permissions(self) -> None:
        codes = set(Group.objects.get(name='App Text Editors').permissions.values_list('codename', flat=True))
        self.assertEqual(codes, {'view_apptext', 'add_apptext', 'change_apptext', 'delete_apptext'})

    def test_an_editor_adds_and_edits_a_string_in_both_languages(self) -> None:
        client = self.client_for(self.staff('App Text Editors'))
        added = client.post(f'{self.LIST}add/', {'key': 'home.title', 'text_en': 'Home', 'text_hi': 'होम', 'is_active': 'on', '_save': 'Save'}, follow=True)
        self.assertEqual(added.status_code, 200)
        item = AppText.objects.get()
        self.assertEqual((item.text_en, item.text_hi), ('Home', 'होम'))
        client.post(f'{self.LIST}{item.pk}/change/', {'key': 'home.title', 'text_en': 'Home page', 'text_hi': '', 'is_active': 'on', '_save': 'Save'}, follow=True)
        item.refresh_from_db()
        self.assertEqual((item.text_en, item.text_hi), ('Home page', ''))

    def test_a_bad_key_is_rejected_by_the_form(self) -> None:
        client = self.client_for(self.staff('App Text Editors'))
        client.post(f'{self.LIST}add/', {'key': 'Bad Key', 'text_en': 'x', 'is_active': 'on', '_save': 'Save'})
        self.assertEqual(AppText.objects.count(), 0)

    def test_other_staff_and_members_cannot_use_it(self) -> None:
        self.text('home.title')
        for user in (self.staff(), self.staff('Content Publishers'), self.staff('Dashboard Managers')):
            client = self.client_for(user)
            self.assertEqual(client.get(self.LIST).status_code, 403)
            self.assertEqual(client.post(f'{self.LIST}add/', {'key': 'x.y', 'text_en': 'x', '_save': 'Save'}).status_code, 403)
        self.assertEqual(AppText.objects.count(), 1)
        self.assertEqual(Client().get(self.LIST).status_code, 302)

    def test_the_missing_hindi_filter_and_search(self) -> None:
        self.text('has.hindi', 'Yes', 'हाँ')
        self.text('no.hindi', 'No')
        client = self.client_for(self.staff('App Text Editors'))
        missing = client.get(f'{self.LIST}?hindi=missing')
        self.assertContains(missing, 'no.hindi')
        self.assertNotContains(missing, 'has.hindi')
        done = client.get(f'{self.LIST}?hindi=done')
        self.assertContains(done, 'has.hindi')
        self.assertNotContains(done, 'no.hindi')
        self.assertContains(client.get(f'{self.LIST}?q=no.hindi'), 'no.hindi')
