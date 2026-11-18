from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from gmp.config import Configurations
from gmp_apps.authentication.models import User
from gmp_apps.common.exceptions.errors import NotFoundError
from gmp_apps.contact_admin.models import ContactCategory, ContactRequest

PASSWORD = 'Sunrise#Valley42'
FAST_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
DESCRIPTION = 'I could not find where to update my address on the profile page.'
CREATE = '/contact_admin/request/create/'


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class ContactBaseTestCase(APITestCase):
    def setUp(self) -> None:
        cache.clear()
        call_command('setup_admin_groups', stdout=StringIO())
        self.counter = 0
        self.category = ContactCategory.objects.get(name='Membership')

    def member(self) -> User:
        self.counter += 1
        return User.objects.create_user(
            full_name=f'Member Number{self.counter}', password=PASSWORD, email=f'm{self.counter}@example.com', email_verified=True,
        )

    def staff(self, *groups: str, superuser: bool = False) -> User:
        self.counter += 1
        if superuser:
            return User.objects.create_superuser(full_name='Super Admin', password=PASSWORD, email=f'su{self.counter}@example.com')
        user = User.objects.create_user(
            full_name='Support Person', password=PASSWORD, email=f'staff{self.counter}@example.com',
            is_staff=True, role='admin', email_verified=True,
        )
        user.groups.add(*Group.objects.filter(name__in=groups))
        return user

    @staticmethod
    def as_user(user: User | None) -> APIClient:
        client = APIClient()
        if user:
            client.force_authenticate(user)
        return client

    def send(self, user: User | None, **overrides):
        payload = {'category_id': self.category.category_id, 'subject': 'Update my address', 'description': DESCRIPTION}
        payload.update(overrides)
        return self.as_user(user).post(CREATE, payload, format='json')

    def make_request(self, user: User, **extra) -> ContactRequest:
        defaults = {'category': self.category, 'subject': 'Hello admin', 'description': DESCRIPTION}
        defaults.update(extra)
        return ContactRequest.objects.create(user=user, **defaults)


class CategoryApiTests(ContactBaseTestCase):
    URL = '/contact_admin/category/get_all/'

    def test_seeded_active_categories_for_members(self) -> None:
        rows = self.as_user(self.member()).get(self.URL).data['data']['data']
        self.assertEqual([r['name'] for r in rows], ['General enquiry', 'Membership', 'Referrals', 'Technical issue', 'Other'])
        self.assertEqual(set(rows[0]), {'categoryId', 'name'})

    def test_inactive_category_is_hidden_and_cannot_be_used(self) -> None:
        ContactCategory.objects.filter(pk=self.category.pk).update(is_active=False)
        member = self.member()
        names = [r['name'] for r in self.as_user(member).get(self.URL).data['data']['data']]
        self.assertNotIn('Membership', names)
        self.assertEqual(self.send(member).status_code, 400)

    def test_search_sort_and_permissions(self) -> None:
        member = self.member()
        found = self.as_user(member).get(f'{self.URL}?search_key=tech').data['data']['data']
        self.assertEqual([r['name'] for r in found], ['Technical issue'])
        self.assertEqual(self.as_user(member).get(f'{self.URL}?sort_by=bad').status_code, 400)
        self.assertEqual(self.as_user(None).get(self.URL).status_code, 401)
        self.assertEqual(self.as_user(self.staff()).get(self.URL).status_code, 403)


class CreateRequestTests(ContactBaseTestCase):
    def test_member_sends_request(self) -> None:
        member = self.member()
        response = self.send(member)
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data['data']
        self.assertEqual((data['status'], data['subject'], data['categoryName']), ('open', 'Update my address', 'Membership'))
        self.assertEqual(data['adminReply'], '')
        item = ContactRequest.objects.get()
        self.assertEqual(item.user_id, member.user_id)

    def test_member_cannot_set_sender_status_or_reply(self) -> None:
        member, other = self.member(), self.member()
        self.send(member, user_id=other.user_id, status='resolved', admin_reply='Done', replied_by=other.user_id)
        item = ContactRequest.objects.get()
        self.assertEqual((item.user_id, item.status, item.admin_reply, item.replied_by_id), (member.user_id, 'open', '', None))

    def test_validation_errors(self) -> None:
        member = self.member()
        bad = (
            {'subject': 'ab'}, {'subject': ''}, {'description': 'too short'}, {'description': 'x' * 5001},
            {'category_id': 999999}, {'category_id': 'abc'}, {'subject': 'x' * 201},
        )
        for override in bad:
            self.assertEqual(self.send(member, **override).status_code, 400, override)
        self.assertEqual(self.as_user(member).post(CREATE, {}, format='json').status_code, 400)
        self.assertEqual(ContactRequest.objects.count(), 0)

    def test_permissions(self) -> None:
        self.assertEqual(self.send(None).status_code, 401)
        self.assertEqual(self.send(self.staff()).status_code, 403)
        self.assertEqual(ContactRequest.objects.count(), 0)

    def test_open_request_cap_counts_only_unresolved(self) -> None:
        member = self.member()
        with mock.patch.object(Configurations, 'contact_max_open_requests', 2):
            codes = [self.send(member).status_code for _ in range(3)]
            self.assertEqual(codes, [200, 200, 400])
            ContactRequest.objects.filter(pk=ContactRequest.objects.filter(user=member).first().pk).update(status='resolved')
            self.assertEqual(self.send(member).status_code, 200)

    def test_daily_cap_is_per_member_and_rolls_off(self) -> None:
        member, other = self.member(), self.member()
        with mock.patch.object(Configurations, 'contact_max_per_day', 2), mock.patch.object(Configurations, 'contact_max_open_requests', 50):
            self.assertEqual([self.send(member).status_code for _ in range(3)], [200, 200, 400])
            self.assertEqual(self.send(other).status_code, 200)
            ContactRequest.objects.filter(user=member).update(created_date_time=timezone.now() - timedelta(days=2))
            self.assertEqual(self.send(member).status_code, 200)

    def test_subject_and_description_are_trimmed(self) -> None:
        self.send(self.member(), subject='  Spaced subject  ', description='   ' + DESCRIPTION + '   ')
        item = ContactRequest.objects.get()
        self.assertEqual((item.subject, item.description), ('Spaced subject', DESCRIPTION))


class ReadRequestTests(ContactBaseTestCase):
    def test_get_own_and_idor(self) -> None:
        owner, intruder = self.member(), self.member()
        item = self.make_request(owner)
        url = f'/contact_admin/request/get/?request_id={item.request_id}'
        self.assertEqual(self.as_user(owner).get(url).data['data']['requestId'], item.request_id)
        self.assertEqual(self.as_user(intruder).get(url).status_code, 404)
        self.assertEqual(self.as_user(owner).get('/contact_admin/request/get/?request_id=999999').status_code, 404)
        self.assertEqual(self.as_user(owner).get('/contact_admin/request/get/').status_code, 400)
        self.assertEqual(self.as_user(None).get(url).status_code, 401)
        self.assertEqual(self.as_user(self.staff()).get(url).status_code, 403)

    def test_list_only_own_with_pagination_filter_search_sort(self) -> None:
        mine, other = self.member(), self.member()
        referrals = ContactCategory.objects.get(name='Referrals')
        for index in range(3):
            self.make_request(mine, subject=f'Mine {index}')
        done = self.make_request(mine, subject='Referral question', category=referrals, status='resolved')
        self.make_request(other, subject='Theirs')
        client = self.as_user(mine)
        everything = client.get('/contact_admin/request/get_all/').data['data']['data']
        self.assertEqual(len(everything), 4)
        self.assertNotIn('Theirs', str(everything))
        page = client.get('/contact_admin/request/get_all/?limit=3').data['data']
        self.assertEqual((len(page['data']), page['totalPage']), (3, 2))
        self.assertIn('nextPageUrl', page)
        by_status = client.get('/contact_admin/request/get_all/?filter_key=status&filter_value=resolved').data['data']['data']
        self.assertEqual([r['requestId'] for r in by_status], [done.request_id])
        by_category = client.get(f'/contact_admin/request/get_all/?filter_key=categoryId&filter_value={referrals.category_id}').data['data']['data']
        self.assertEqual([r['requestId'] for r in by_category], [done.request_id])
        found = client.get('/contact_admin/request/get_all/?search_key=Referral question').data['data']['data']
        self.assertEqual(len(found), 1)
        ordered = client.get('/contact_admin/request/get_all/?sort_by=subject&sort_order=asc').data['data']['data']
        self.assertEqual(ordered[0]['subject'], 'Mine 0')
        values = client.get('/contact_admin/request/get_all/?values=requestId,status').data['data']['data']
        self.assertEqual(set(values[0]), {'requestId', 'status'})
        self.assertEqual(client.get('/contact_admin/request/get_all/?filter_key=user_id&filter_value=1').status_code, 400)
        self.assertEqual(client.get('/contact_admin/request/get_all/?page_num=9').status_code, 400)

    def test_list_permissions(self) -> None:
        self.assertEqual(self.as_user(None).get('/contact_admin/request/get_all/').status_code, 401)
        self.assertEqual(self.as_user(self.staff()).get('/contact_admin/request/get_all/').status_code, 403)


class ModelRuleTests(ContactBaseTestCase):
    def test_respond_rules(self) -> None:
        admin, member = self.staff('Support Handlers'), self.member()
        item = self.make_request(member)
        with self.assertRaises(ValueError):
            ContactRequest.respond(item.pk, admin, 'resolved', '  ')
        with self.assertRaises(ValueError):
            ContactRequest.respond(item.pk, admin, 'nonsense', 'x')
        with self.assertRaises(NotFoundError):
            ContactRequest.respond(999999, admin, 'open', '')
        answered = ContactRequest.respond(item.pk, admin, 'open', 'We are on it')
        self.assertEqual((answered.status, answered.replied_by_id), ('in_progress', admin.user_id))
        closed = ContactRequest.respond(item.pk, admin, 'closed', 'We are on it')
        self.assertEqual(closed.status, 'closed')
        with self.assertRaises(ValueError):
            ContactRequest.respond(item.pk, admin, 'open', 'reopen?')

    def test_reply_author_only_changes_when_reply_text_changes(self) -> None:
        first, second, member = self.staff('Support Handlers'), self.staff('Support Handlers'), self.member()
        item = self.make_request(member)
        ContactRequest.respond(item.pk, first, 'in_progress', 'First reply')
        again = ContactRequest.respond(item.pk, second, 'resolved', 'First reply')
        self.assertEqual(again.replied_by_id, first.user_id)
        edited = ContactRequest.respond(item.pk, second, 'resolved', 'Edited reply')
        self.assertEqual(edited.replied_by_id, second.user_id)


class AdminHandlingTests(ContactBaseTestCase):
    LIST = '/admin/contact_admin/contactrequest/'

    def url(self, item: ContactRequest) -> str:
        return f'{self.LIST}{item.pk}/change/'

    @staticmethod
    def client_for(user: User | None) -> Client:
        client = Client()
        if user:
            client.force_login(user)
        return client

    def answer(self, actor: User, item: ContactRequest, status: str, reply: str):
        return self.client_for(actor).post(self.url(item), {'status': status, 'admin_reply': reply, '_save': 'Save'}, follow=True)

    def test_support_handler_sees_list_search_filter_and_detail(self) -> None:
        handler = self.staff('Support Handlers')
        member = self.member()
        item = self.make_request(member, subject='Unique subject phrase')
        self.make_request(self.member(), status='resolved')
        client = self.client_for(handler)
        self.assertEqual(client.get(self.LIST).status_code, 200)
        found = client.get(f'{self.LIST}?q=Unique subject phrase').context['cl'].result_list
        self.assertEqual([r.pk for r in found], [item.pk])
        by_member = client.get(f'{self.LIST}?q={member.membership_id}').context['cl'].result_list
        self.assertEqual([r.pk for r in by_member], [item.pk])
        open_only = client.get(f'{self.LIST}?status__exact=open').context['cl'].result_list
        self.assertEqual([r.pk for r in open_only], [item.pk])
        page = client.get(self.url(item))
        self.assertContains(page, 'Unique subject phrase')
        self.assertContains(page, DESCRIPTION)

    def test_reply_is_saved_and_visible_to_the_member_without_admin_identity(self) -> None:
        handler, member = self.staff('Support Handlers'), self.member()
        item = self.make_request(member)
        self.answer(handler, item, 'resolved', 'Open Profile > Edit to change your address.')
        item.refresh_from_db()
        self.assertEqual((item.status, item.replied_by_id), ('resolved', handler.user_id))
        response = self.as_user(member).get(f'/contact_admin/request/get/?request_id={item.request_id}')
        self.assertEqual(response.data['data']['adminReply'], 'Open Profile > Edit to change your address.')
        self.assertEqual(response.data['data']['status'], 'resolved')
        self.assertNotIn(handler.email, str(response.data))
        self.assertNotIn(handler.full_name, str(response.data))
        self.assertNotIn('repliedBy', response.data['data'])

    def test_reply_on_open_request_moves_it_to_in_progress(self) -> None:
        handler = self.staff('Support Handlers')
        item = self.make_request(self.member())
        self.answer(handler, item, 'open', 'Looking into it')
        item.refresh_from_db()
        self.assertEqual(item.status, 'in_progress')

    def test_resolving_or_closing_needs_a_reply(self) -> None:
        handler = self.staff('Support Handlers')
        item = self.make_request(self.member())
        response = self.answer(handler, item, 'resolved', '')
        item.refresh_from_db()
        self.assertEqual(item.status, 'open')
        self.assertContains(response, 'A reply is required')

    def test_closed_request_is_final(self) -> None:
        handler = self.staff('Support Handlers')
        item = self.make_request(self.member())
        self.answer(handler, item, 'closed', 'Closing this')
        response = self.answer(handler, item, 'open', 'reopen')
        item.refresh_from_db()
        self.assertEqual((item.status, item.admin_reply), ('closed', 'Closing this'))
        self.assertContains(response, 'closed and cannot be changed')

    def test_member_content_is_read_only_and_no_add_or_delete(self) -> None:
        handler = self.staff('Support Handlers')
        item = self.make_request(self.member(), subject='Original subject')
        self.client_for(handler).post(self.url(item), {
            'status': 'open', 'admin_reply': '', 'subject': 'Tampered', 'description': 'Tampered description here', '_save': 'Save',
        })
        item.refresh_from_db()
        self.assertEqual((item.subject, item.description), ('Original subject', DESCRIPTION))
        self.assertEqual(self.client_for(handler).get(self.LIST + 'add/').status_code, 403)
        self.assertEqual(self.client_for(handler).get(self.url(item).replace('change/', 'delete/')).status_code, 403)
        self.assertTrue(ContactRequest.objects.filter(pk=item.pk).exists())

    def test_only_permitted_staff_can_handle_requests(self) -> None:
        item = self.make_request(self.member())
        for blocked in (self.staff(), self.staff('Member Managers'), self.staff('Membership Reviewers')):
            client = self.client_for(blocked)
            self.assertEqual(client.get(self.LIST).status_code, 403)
            self.answer(blocked, item, 'resolved', 'sneaky')
        self.assertEqual(Client().get(self.LIST).status_code, 302)
        self.assertEqual(self.client_for(self.member()).get(self.LIST).status_code, 302)
        item.refresh_from_db()
        self.assertEqual((item.status, item.admin_reply), ('open', ''))
        self.assertEqual(self.client_for(self.staff(superuser=True)).get(self.LIST).status_code, 200)

    def test_support_handlers_cannot_see_members_or_membership_data(self) -> None:
        client = self.client_for(self.staff('Support Handlers'))
        for path in ('/admin/authentication/user/', '/admin/membership/referral/', '/admin/membership/permanentapplication/'):
            self.assertEqual(client.get(path).status_code, 403, path)

    def test_category_management_by_support_handlers(self) -> None:
        handler = self.staff('Support Handlers')
        client = self.client_for(handler)
        self.assertEqual(client.get('/admin/contact_admin/contactcategory/').status_code, 200)
        client.post('/admin/contact_admin/contactcategory/add/', {'name': 'Events', 'sort_order': 9, 'is_active': 'on', '_save': 'Save'})
        self.assertTrue(ContactCategory.objects.filter(name='Events', is_active=True).exists())
        names = [r['name'] for r in self.as_user(self.member()).get('/contact_admin/category/get_all/').data['data']['data']]
        self.assertIn('Events', names)
        category = ContactCategory.objects.get(name='Events')
        self.assertEqual(client.get(f'/admin/contact_admin/contactcategory/{category.pk}/delete/').status_code, 403)

    def test_deactivated_category_keeps_old_requests_readable(self) -> None:
        member = self.member()
        item = self.make_request(member)
        ContactCategory.objects.filter(pk=self.category.pk).update(is_active=False)
        response = self.as_user(member).get(f'/contact_admin/request/get/?request_id={item.request_id}')
        self.assertEqual(response.data['data']['categoryName'], 'Membership')

    def test_dashboard_card_follows_permission(self) -> None:
        self.make_request(self.member())
        self.make_request(self.member(), status='resolved')

        def cards(user: User) -> dict[str, int]:
            return {c['title']: c['value'] for c in self.client_for(user).get('/admin/').context['dashboard_cards']}

        self.assertEqual(cards(self.staff('Support Handlers')), {'Open contact requests': 1})
        self.assertNotIn('Open contact requests', cards(self.staff('Member Managers')))
        self.assertEqual(cards(self.staff(superuser=True))['Open contact requests'], 1)


class SwaggerTests(ContactBaseTestCase):
    def test_all_paths_in_schema(self) -> None:
        body = APIClient().get('/api/schema/').content.decode()
        for path in ('category/get_all', 'request/create', 'request/get', 'request/get_all'):
            self.assertIn(f'/contact_admin/{path}/', body)
