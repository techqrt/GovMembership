from io import StringIO

from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.test import Client, TestCase, override_settings
from rest_framework.test import APIClient, APITestCase

from gmp.config import Configurations
from gmp_apps.authentication.models import User
from gmp_apps.portals.models import ComplaintPortal, PortalCategory
from gmp_apps.portals.validators import url_key, validate_portal_url

PASSWORD = 'Sunrise#Valley42'
FAST_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']


class UrlValidatorTests(TestCase):
    def test_plain_public_web_urls_are_accepted(self) -> None:
        for good in ('https://pgportal.gov.in', 'https://pgportal.gov.in/', 'http://old.example.gov.in/path/page.html',
                     'https://portal.example.in:8443/grievance?lang=en', 'https://a.b.c.example.org/x#frag', 'https://8.8.8.8/'):
            validate_portal_url(good)

    def test_unsafe_or_malformed_urls_are_refused(self) -> None:
        bad = (
            'javascript:alert(1)', 'JAVASCRIPT:alert(1)', 'data:text/html,<script>alert(1)</script>', 'ftp://files.example.gov.in/x',
            'file:///etc/passwd', 'mailto:a@b.co', 'tel:+911234', '//example.gov.in/x', 'example.gov.in', '', 'https://',
            'https://user:pass@example.gov.in/', 'https://user@example.gov.in/', 'https://exa mple.gov.in/', 'https://example.gov.in/a b',
            'https://example.gov.in/\x01', 'https://example.gov.in/\nHost: evil', 'http://intranet', 'https://example.gov.in./',
            'https://localhost/', 'https://127.0.0.1/', 'https://10.1.2.3/', 'https://192.168.0.5/', 'https://169.254.169.254/latest',
            'https://[::1]/', 'https://example.gov.in:99999/', 'https://example.gov.in:abc/', 'https://' + 'a' * 600 + '.gov.in/',
            'javascript://example.gov.in/%0Aalert(1)', 'vbscript://example.gov.in/x',
        )
        for value in bad:
            with self.assertRaises(ValidationError, msg=value[:60]):
                validate_portal_url(value)

    def test_length_limit_comes_from_configuration(self) -> None:
        from unittest import mock

        with mock.patch.object(Configurations, 'portal_url_max_length', 30):
            validate_portal_url('https://a.gov.in/x')
            with self.assertRaises(ValidationError):
                validate_portal_url('https://a.gov.in/' + 'x' * 30)

    def test_canonical_key_ignores_case_fragment_trailing_slash_and_default_ports(self) -> None:
        same = {'https://PGPortal.GOV.in/', 'https://pgportal.gov.in', 'HTTPS://pgportal.gov.in:443/', 'https://pgportal.gov.in/#top'}
        self.assertEqual({url_key(u) for u in same}, {'https://pgportal.gov.in'})
        self.assertEqual(url_key('http://a.gov.in:80/x/'), 'http://a.gov.in/x')

    def test_canonical_key_keeps_what_makes_portals_different(self) -> None:
        keys = {url_key(u) for u in ('https://a.gov.in/one', 'https://a.gov.in/two', 'https://a.gov.in/one?id=1', 'http://a.gov.in/one',
                                     'https://a.gov.in:8443/one', 'https://b.gov.in/one')}
        self.assertEqual(len(keys), 6)


class ModelTests(TestCase):
    def setUp(self) -> None:
        self.category = PortalCategory.objects.get(name='General')

    def portal(self, url: str = 'https://pgportal.gov.in', **extra) -> ComplaintPortal:
        return ComplaintPortal.objects.create(name=extra.pop('name', 'Portal'), official_url=url, category=self.category, **extra)

    def test_seeded_categories(self) -> None:
        self.assertEqual(list(PortalCategory.objects.values_list('name', flat=True)), ['General', 'Other'])

    def test_every_save_validates_the_link_not_only_forms(self) -> None:
        for bad in ('javascript:alert(1)', 'https://user:pw@a.gov.in', 'https://10.0.0.1/', 'not a url'):
            with self.assertRaises(ValidationError, msg=bad):
                self.portal(bad)
        portal = self.portal()
        portal.official_url = 'javascript:alert(1)'
        with self.assertRaises(ValidationError):
            portal.save()
        portal.refresh_from_db()
        self.assertEqual(portal.official_url, 'https://pgportal.gov.in')

    def test_url_is_trimmed_and_key_is_stored(self) -> None:
        portal = self.portal('  https://PGPortal.gov.in/  ')
        self.assertEqual((portal.official_url, portal.url_key), ('https://PGPortal.gov.in/', 'https://pgportal.gov.in'))

    def test_the_same_portal_cannot_be_listed_twice_in_any_spelling(self) -> None:
        self.portal('https://pgportal.gov.in')
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.portal('HTTPS://PGPORTAL.GOV.IN/')
        duplicate = ComplaintPortal(name='Again', official_url='https://pgportal.gov.in/#x', category=self.category)
        with self.assertRaises(ValidationError):
            duplicate.full_clean()
        self.portal('https://pgportal.gov.in/other')  # a different page is a different portal

    def test_uniqueness_is_declared_on_the_model_and_present_in_the_database(self) -> None:
        self.assertTrue(ComplaintPortal._meta.get_field('url_key').unique)
        with transaction.atomic(), connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(cursor, ComplaintPortal._meta.db_table)
        self.assertTrue(any(c['unique'] and c['columns'] == ['url_key'] for c in constraints.values()))

    def test_editing_a_portal_does_not_clash_with_itself(self) -> None:
        portal = self.portal()
        portal.name = 'Renamed'
        portal.full_clean()
        portal.save()

    def test_a_category_with_portals_cannot_be_deleted(self) -> None:
        self.portal()
        with self.assertRaises(ProtectedError):
            self.category.delete()
        PortalCategory.objects.get(name='Other').delete()  # an empty one can go


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class PortalApiBase(APITestCase):
    def setUp(self) -> None:
        cache.clear()
        call_command('setup_admin_groups', stdout=StringIO())
        self.counter = 0
        self.general = PortalCategory.objects.get(name='General')

    def member(self) -> User:
        self.counter += 1
        return User.objects.create_user(full_name=f'Member {self.counter}', password=PASSWORD, email=f'm{self.counter}@example.com', email_verified=True)

    def staff(self, *groups: str, role: str = 'admin') -> User:
        self.counter += 1
        user = User.objects.create_user(full_name='Staff', password=PASSWORD, email=f'st{self.counter}@example.com', is_staff=True, role=role, email_verified=True)
        user.groups.add(*Group.objects.filter(name__in=groups))
        return user

    @staticmethod
    def as_user(user: User | None) -> APIClient:
        client = APIClient()
        if user:
            client.force_authenticate(user)
        return client

    def portal(self, name: str = 'Portal', url: str | None = None, **extra) -> ComplaintPortal:
        self.counter += 1
        extra.setdefault('category', self.general)
        return ComplaintPortal.objects.create(name=name, official_url=url or f'https://portal{self.counter}.gov.in', **extra)


class MemberPortalApiTests(PortalApiBase):
    LIST = '/portals/get_all/'

    def test_only_active_portals_of_active_categories_are_listed(self) -> None:
        self.portal('Visible')
        self.portal('Switched off', is_active=False)
        hidden_category = PortalCategory.objects.create(name='Hidden group', is_active=False)
        self.portal('In hidden category', category=hidden_category)
        rows = self.as_user(self.member()).get(self.LIST).data['data']['data']
        self.assertEqual([r['name'] for r in rows], ['Visible'])

    def test_row_shape_is_exactly_what_a_member_needs(self) -> None:
        portal = self.portal('CPGRAMS', 'https://pgportal.gov.in/', description='Central public grievances', department='DARPG', sort_order=3)
        response = self.as_user(self.member()).get(self.LIST)
        row = response.data['data']['data'][0]
        self.assertEqual(row, {
            'portalId': portal.portal_id, 'name': 'CPGRAMS', 'description': 'Central public grievances', 'department': 'DARPG',
            'categoryId': self.general.category_id, 'categoryName': 'General', 'officialUrl': 'https://pgportal.gov.in/',
            'fileComplaintUrl': None, 'trackStatusUrl': None,
        })
        for internal in ('isActive', 'urlKey', 'sortOrder', 'createdDateTime', 'updatedDateTime'):
            self.assertNotIn(internal, str(response.data['data']))

    def test_default_order_is_category_then_portal_order_then_name(self) -> None:
        other = PortalCategory.objects.get(name='Other')
        self.portal('Zeta', category=self.general, sort_order=1)
        self.portal('Alpha', category=self.general, sort_order=1)
        self.portal('First by order', category=self.general, sort_order=0)
        self.portal('In other', category=other)
        names = [r['name'] for r in self.as_user(self.member()).get(self.LIST).data['data']['data']]
        self.assertEqual(names, ['First by order', 'Alpha', 'Zeta', 'In other'])

    def test_pagination_filter_search_sort_values_dates(self) -> None:
        consumer = PortalCategory.objects.create(name='Consumer', sort_order=5)
        for index in range(5):
            self.portal(f'General {index}', department='Dept A' if index < 3 else 'Dept B')
        self.portal('Consumer helpline', category=consumer, description='Product complaints')
        client = self.as_user(self.member())
        page = client.get(f'{self.LIST}?limit=4').data['data']
        self.assertEqual((len(page['data']), page['totalPage']), (4, 2))
        self.assertIn('nextPageUrl', page)
        by_cat = client.get(f'{self.LIST}?filter_key=categoryId&filter_value={consumer.category_id}').data['data']['data']
        self.assertEqual([r['name'] for r in by_cat], ['Consumer helpline'])
        by_dept = client.get(f'{self.LIST}?filter_key=department&filter_value=Dept B').data['data']['data']
        self.assertEqual(len(by_dept), 2)
        self.assertEqual([r['name'] for r in client.get(f'{self.LIST}?search_key=product').data['data']['data']], ['Consumer helpline'])
        self.assertEqual(len(client.get(f'{self.LIST}?search_key=Consumer').data['data']['data']), 1)  # matches category name too
        desc = client.get(f'{self.LIST}?sort_by=name&sort_order=desc').data['data']['data']
        self.assertEqual(desc[0]['name'], 'General 4')
        self.assertEqual(set(client.get(f'{self.LIST}?values=portalId,name').data['data']['data'][0]), {'portalId', 'name'})
        self.assertEqual(len(client.get(f'{self.LIST}?from_date=01-01-20').data['data']['data']), 6)
        self.assertEqual(client.get(f'{self.LIST}?sort_by=isActive').status_code, 400)
        self.assertEqual(client.get(f'{self.LIST}?filter_key=isActive&filter_value=1').status_code, 400)
        self.assertEqual(client.get(f'{self.LIST}?filter_key=urlKey&filter_value=x').status_code, 400)
        self.assertEqual(client.get(f'{self.LIST}?page_num=9').status_code, 400)

    def test_search_cannot_reach_inactive_portals_or_internal_columns(self) -> None:
        self.portal('Off', is_active=False, description='secret wording')
        self.portal('On', url='https://secretkey.gov.in')
        client = self.as_user(self.member())
        self.assertEqual(client.get(f'{self.LIST}?search_key=secret').data['data']['data'], [])
        self.assertEqual(client.get(f'{self.LIST}?search_key=pgportal').data['data']['data'], [])

    def test_get_one_and_404s(self) -> None:
        live = self.portal('Live')
        off = self.portal('Off', is_active=False)
        in_hidden = self.portal('Hidden cat', category=PortalCategory.objects.create(name='Gone', is_active=False))
        client = self.as_user(self.member())
        self.assertEqual(client.get(f'/portals/get/?portal_id={live.portal_id}').data['data']['name'], 'Live')
        for portal in (off, in_hidden):
            self.assertEqual(client.get(f'/portals/get/?portal_id={portal.portal_id}').status_code, 404)
        self.assertEqual(client.get('/portals/get/?portal_id=999999').status_code, 404)
        self.assertEqual(client.get('/portals/get/').status_code, 400)
        self.assertEqual(client.get('/portals/get/?portal_id=abc').status_code, 400)

    def test_categories_in_use_with_counts(self) -> None:
        consumer = PortalCategory.objects.create(name='Consumer', sort_order=1)
        PortalCategory.objects.create(name='Empty one')
        PortalCategory.objects.create(name='Hidden one', is_active=False)
        self.portal('A')
        self.portal('B')
        self.portal('C', is_active=False)
        self.portal('D', category=consumer)
        self.portal('E', category=PortalCategory.objects.get(name='Hidden one'))
        data = self.as_user(self.member()).get('/portals/category/get_all/').data['data']['data']
        self.assertEqual(data, [{'categoryId': self.general.category_id, 'name': 'General', 'portalCount': 2},
                                {'categoryId': consumer.category_id, 'name': 'Consumer', 'portalCount': 1}])

    def test_authentication_and_roles_on_every_endpoint(self) -> None:
        portal = self.portal()
        for path in (self.LIST, f'/portals/get/?portal_id={portal.portal_id}', '/portals/category/get_all/'):
            self.assertEqual(self.as_user(None).get(path).status_code, 401, path)
            self.assertEqual(self.as_user(self.staff('Portal Managers')).get(path).status_code, 403, path)
            self.assertEqual(self.as_user(self.member()).get(path).status_code, 200, path)

    def test_the_list_costs_a_fixed_number_of_queries(self) -> None:
        for index in range(8):
            self.portal(f'P{index}')
        client = self.as_user(self.member())
        with self.assertNumQueries(2):  # count + one page (category joined)
            client.get(self.LIST)

    def test_the_platform_exposes_no_way_to_file_or_track_a_complaint(self) -> None:
        client = self.as_user(self.member())
        for method in ('post', 'put', 'patch', 'delete'):
            self.assertEqual(getattr(client, method)(self.LIST, {}, format='json').status_code, 405, method)
        schema = APIClient().get('/api/schema/').content.decode()
        self.assertEqual(sorted(p for p in ('/portals/get_all/', '/portals/get/', '/portals/category/get_all/') if p in schema),
                         ['/portals/category/get_all/', '/portals/get/', '/portals/get_all/'])
        self.assertNotIn('/portals/create', schema)
        self.assertNotIn('complaint/', schema)


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class PortalAdminTests(PortalApiBase):
    LIST = '/admin/portals/complaintportal/'
    CATS = '/admin/portals/portalcategory/'

    def setUp(self) -> None:
        super().setUp()
        self.manager = self.staff('Portal Managers')
        self.client_ = Client()
        self.client_.force_login(self.manager)

    def form(self, **overrides) -> dict:
        data = {'name': 'CPGRAMS', 'category': self.general.pk, 'department': 'DARPG', 'description': 'Central grievances',
                'official_url': 'https://pgportal.gov.in/', 'sort_order': '0', 'is_active': 'on', '_save': 'Save'}
        data.update(overrides)
        return {k: v for k, v in data.items() if v != ''}

    def test_add_edit_delete_a_portal(self) -> None:
        self.client_.post(self.LIST + 'add/', self.form(), follow=True)
        portal = ComplaintPortal.objects.get()
        self.assertEqual((portal.name, portal.url_key, portal.is_active), ('CPGRAMS', 'https://pgportal.gov.in', True))
        self.client_.post(f'{self.LIST}{portal.pk}/change/', self.form(name='CPGRAMS (renamed)', official_url='https://pgportal.gov.in/new'), follow=True)
        portal.refresh_from_db()
        self.assertEqual((portal.name, portal.official_url), ('CPGRAMS (renamed)', 'https://pgportal.gov.in/new'))
        self.client_.post(f'{self.LIST}{portal.pk}/delete/', {'post': 'yes'}, follow=True)
        self.assertFalse(ComplaintPortal.objects.exists())

    def test_unsafe_or_duplicate_links_are_rejected_with_nothing_saved(self) -> None:
        self.portal('Existing', 'https://pgportal.gov.in')
        for bad in ('javascript:alert(1)', 'https://user:pw@a.gov.in/', 'https://10.0.0.1/', 'ftp://a.gov.in/', 'http://intranet',
                    'HTTPS://PGPORTAL.GOV.IN/', 'https://pgportal.gov.in/#x'):
            response = self.client_.post(self.LIST + 'add/', self.form(name='Bad', official_url=bad))
            self.assertEqual(response.status_code, 200, bad)  # form re-shown with an error, no redirect
        self.assertEqual(ComplaintPortal.objects.count(), 1)

    def test_editing_into_a_duplicate_is_rejected(self) -> None:
        first = self.portal('One', 'https://one.gov.in')
        self.portal('Two', 'https://two.gov.in')
        self.client_.post(f'{self.LIST}{first.pk}/change/', self.form(name='One', official_url='https://two.gov.in/'))
        first.refresh_from_db()
        self.assertEqual(first.official_url, 'https://one.gov.in')

    def test_activate_and_deactivate_drive_member_visibility(self) -> None:
        portal = self.portal('Toggle')
        member = self.as_user(self.member())
        self.assertEqual(len(member.get('/portals/get_all/').data['data']['data']), 1)
        self.client_.post(self.LIST, {'action': 'deactivate_portals', '_selected_action': [portal.pk]}, follow=True)
        portal.refresh_from_db()
        self.assertFalse(portal.is_active)
        self.assertEqual(member.get('/portals/get_all/').data['data']['data'], [])
        self.assertEqual(member.get(f'/portals/get/?portal_id={portal.portal_id}').status_code, 404)
        self.client_.post(self.LIST, {'action': 'activate_portals', '_selected_action': [portal.pk]}, follow=True)
        self.assertEqual(len(member.get('/portals/get_all/').data['data']['data']), 1)

    def test_list_search_filter_and_safe_rendering(self) -> None:
        self.portal('Alpha <script>alert(1)</script>', 'https://alpha.gov.in', department='Health')
        self.portal('Beta', 'https://beta.gov.in', is_active=False)
        page = self.client_.get(self.LIST)
        body = page.content.decode()
        self.assertNotIn('<script>alert(1)</script>', body)
        self.assertIn('rel="noopener noreferrer"', body)
        self.assertIn('target="_blank"', body)
        self.assertEqual([p.name for p in self.client_.get(f'{self.LIST}?q=beta.gov.in').context['cl'].result_list], ['Beta'])
        self.assertEqual(len(self.client_.get(f'{self.LIST}?is_active__exact=0').context['cl'].result_list), 1)
        self.assertEqual(len(self.client_.get(f'{self.LIST}?q=Health').context['cl'].result_list), 1)

    def test_category_management_and_protection(self) -> None:
        self.client_.post(self.CATS + 'add/', {'name': 'Consumer', 'sort_order': '3', 'is_active': 'on', '_save': 'Save'}, follow=True)
        consumer = PortalCategory.objects.get(name='Consumer')
        self.portal('In general')
        self.client_.post(f'{self.CATS}{self.general.pk}/delete/', {'post': 'yes'}, follow=True)
        self.assertTrue(PortalCategory.objects.filter(pk=self.general.pk).exists())   # protected: it still has a portal
        self.assertEqual(ComplaintPortal.objects.count(), 1)
        self.client_.post(f'{self.CATS}{consumer.pk}/delete/', {'post': 'yes'}, follow=True)
        self.assertFalse(PortalCategory.objects.filter(pk=consumer.pk).exists())       # empty: can go

    def test_deactivating_a_category_hides_its_portals_from_members(self) -> None:
        self.portal('Listed')
        member = self.as_user(self.member())
        self.client_.post(f'{self.CATS}{self.general.pk}/change/', {'name': 'General', 'sort_order': '0', '_save': 'Save'}, follow=True)  # is_active unchecked
        self.general.refresh_from_db()
        self.assertFalse(self.general.is_active)
        self.assertEqual(member.get('/portals/get_all/').data['data']['data'], [])
        self.assertEqual(member.get('/portals/category/get_all/').data['data']['data'], [])

    def test_only_portal_managers_and_superusers_can_use_the_directory_admin(self) -> None:
        portal = self.portal()
        for blocked in (self.staff(), self.staff('Support Handlers'), self.staff('Scheme Reviewers'), self.staff('Member Managers'), self.staff('Membership Reviewers')):
            client = Client()
            client.force_login(blocked)
            self.assertEqual(client.get(self.LIST).status_code, 403)
            self.assertEqual(client.get(self.CATS).status_code, 403)
            client.post(self.LIST + 'add/', self.form(name='Sneaky', official_url='https://sneaky.gov.in'))
            client.post(self.LIST, {'action': 'deactivate_portals', '_selected_action': [portal.pk]})
        portal.refresh_from_db()
        self.assertEqual((ComplaintPortal.objects.count(), portal.is_active), (1, True))
        self.assertEqual(Client().get(self.LIST).status_code, 302)
        member_client = Client()
        member_client.force_login(self.member())
        self.assertEqual(member_client.get(self.LIST).status_code, 302)
        root = User.objects.create_superuser(full_name='Root', password=PASSWORD, email='root@example.com')
        superuser = Client()
        superuser.force_login(root)
        self.assertEqual(superuser.get(self.LIST).status_code, 200)

    def test_portal_managers_see_nothing_else(self) -> None:
        for path in ('/admin/authentication/user/', '/admin/membership/referral/', '/admin/schemes/scheme/', '/admin/contact_admin/contactrequest/'):
            self.assertEqual(self.client_.get(path).status_code, 403, path)

    def test_group_permissions_are_exact(self) -> None:
        codes = set(Group.objects.get(name='Portal Managers').permissions.values_list('codename', flat=True))
        self.assertEqual(codes, {f'{a}_{m}' for a in ('view', 'add', 'change', 'delete') for m in ('complaintportal', 'portalcategory')})

    def test_dashboard_cards_follow_permission(self) -> None:
        self.portal('On')
        self.portal('Off', is_active=False)

        def cards(user: User) -> dict[str, int]:
            client = Client()
            client.force_login(user)
            return {c['title']: c['value'] for c in client.get('/admin/').context['dashboard_cards']}

        self.assertEqual(cards(self.manager), {'Active complaint portals': 1, 'Inactive complaint portals': 1})
        self.assertNotIn('Active complaint portals', cards(self.staff('Support Handlers')))


class SwaggerTests(PortalApiBase):
    def test_paths_in_schema(self) -> None:
        body = APIClient().get('/api/schema/').content.decode()
        for path in ('get_all', 'get', 'category/get_all'):
            self.assertIn(f'/portals/{path}/', body)
