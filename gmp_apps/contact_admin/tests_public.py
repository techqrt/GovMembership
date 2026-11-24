"""FG9: the public Contact Us form (no login) and its topics."""
import importlib
from io import StringIO

from django.apps import apps as django_apps
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import Client, override_settings
from rest_framework.test import APIClient, APITestCase

from gmp_apps.authentication.models import User
from gmp_apps.contact_admin.dataclasses.request.create.create_public_request import CreatePublicRequestRequest
from gmp_apps.contact_admin.models import ContactCategory, ContactRequest
from gmp_apps.contact_admin.views.public import ContactPublicView
from gmp_apps.notifications.models import Notification

FAST_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
PASSWORD = 'Sunrise#Valley42'
CREATE = '/contact/request/create/'
CATEGORIES = '/contact/category/get_all/'
TOPICS = ['Membership', 'Schemes', 'Complaints', 'Any other']
QUERY = 'I could not find where to check the status of my scheme application.'


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class PublicBase(APITestCase):
    def setUp(self) -> None:
        cache.clear()
        call_command('setup_admin_groups', stdout=StringIO())
        self.counter = 0
        self.topic = {c.name: c for c in ContactCategory.objects.filter(is_active=True)}

    def member(self) -> User:
        self.counter += 1
        return User.objects.create_user(full_name=f'Member {self.counter}', password=PASSWORD, email=f'm{self.counter}@example.com', email_verified=True)

    def staff(self, *groups: str) -> User:
        self.counter += 1
        user = User.objects.create_user(full_name='Staff', password=PASSWORD, email=f's{self.counter}@example.com', is_staff=True, role='admin', email_verified=True)
        user.groups.add(*Group.objects.filter(name__in=groups))
        return user

    def send(self, client: APIClient | None = None, **overrides):
        payload = {'category_id': self.topic['Membership'].category_id, 'full_name': 'Asha Verma', 'email': 'asha@example.com', 'description': QUERY}
        payload.update(overrides)
        payload = {k: v for k, v in payload.items() if v is not Ellipsis}
        return (client or APIClient()).post(CREATE, payload, format='json')


class PublicTopicTests(PublicBase):
    def test_exactly_four_topics_in_order_for_a_visitor(self) -> None:
        response = APIClient().get(CATEGORIES)
        self.assertEqual(response.status_code, 200)
        rows = response.data['data']['data']
        self.assertEqual([r['name'] for r in rows], TOPICS)
        self.assertEqual(set(rows[0]), {'categoryId', 'name'})

    def test_old_categories_are_kept_but_hidden(self) -> None:
        old = ContactCategory.objects.get(name='Technical issue')
        self.assertFalse(old.is_active)
        self.assertEqual(self.send(category_id=old.category_id).status_code, 400)
        self.assertNotIn('Technical issue', [r['name'] for r in APIClient().get(CATEGORIES).data['data']['data']])

    def test_a_category_with_requests_survives_the_migration(self) -> None:
        old = ContactCategory.objects.get(name='Referrals')
        ContactRequest.objects.create(user=self.member(), category=old, subject='Old one', description='An older request on a hidden topic')
        module = importlib.import_module('gmp_apps.contact_admin.migrations.0005_public_contact_categories')
        module.set_public_categories(django_apps, None)       # running it again changes nothing and deletes nothing
        old.refresh_from_db()
        self.assertFalse(old.is_active)
        self.assertEqual(ContactRequest.objects.filter(category=old).count(), 1)
        self.assertEqual([c.name for c in ContactCategory.objects.filter(is_active=True)], TOPICS)

    def test_an_admin_deactivated_topic_leaves_the_dropdown(self) -> None:
        ContactCategory.objects.filter(name='Schemes').update(is_active=False)
        self.assertEqual([r['name'] for r in APIClient().get(CATEGORIES).data['data']['data']], ['Membership', 'Complaints', 'Any other'])

    def test_topics_are_rate_limited_in_their_own_bucket(self) -> None:
        codes = [APIClient().get(CATEGORIES).status_code for _ in range(62)]
        self.assertEqual(codes[:60], [200] * 60)
        self.assertEqual(codes[-1], 429)
        self.assertEqual(self.send().status_code, 200)          # the form has its own budget

    def test_members_see_the_same_four_topics(self) -> None:
        rows = APIClient()
        rows.force_authenticate(self.member())
        self.assertEqual([r['name'] for r in rows.get('/contact_admin/category/get_all/').data['data']['data']], TOPICS)


class PublicCreateTests(PublicBase):
    def test_each_of_the_four_topics_is_stored_as_a_guest_request(self) -> None:
        for name in TOPICS:
            cache.clear()
            response = self.send(category_id=self.topic[name].category_id, full_name=f'Guest {name}')
            self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(ContactRequest.objects.count(), 4)
        for item in ContactRequest.objects.all():
            self.assertIsNone(item.user_id)
            self.assertEqual((item.status, item.priority, item.admin_reply), ('open', 'normal', ''))
        self.assertEqual({i.category.name for i in ContactRequest.objects.all()}, set(TOPICS))

    def test_the_answer_is_a_plain_received_message_with_nothing_to_look_up(self) -> None:
        response = self.send()
        self.assertEqual(set(response.data), {'status', 'message'})
        self.assertTrue(response.data['status'])
        text = response.content.decode().lower()
        for leaked in ('requestid', 'request_id', 'asha@example.com', 'asha verma'):
            self.assertNotIn(leaked, text)

    def test_blank_subject_stays_blank_whatever_way_it_is_left_out(self) -> None:
        for extra in ({}, {'subject': ''}, {'subject': None}, {'subject': '   '}):
            cache.clear()
            self.assertEqual(self.send(**extra).status_code, 200, extra)
        self.assertEqual(set(ContactRequest.objects.values_list('subject', flat=True)), {''})

    def test_a_subject_that_is_sent_is_kept(self) -> None:
        self.send(subject='  Scheme status ')
        self.assertEqual(ContactRequest.objects.get().subject, 'Scheme status')

    def test_name_is_required_and_a_contact_is_required(self) -> None:
        self.assertEqual(self.send(full_name=Ellipsis).status_code, 400)
        self.assertEqual(self.send(full_name='A').status_code, 400)
        for gone in ({'email': Ellipsis}, {'email': ''}, {'email': None}):
            response = self.send(**gone)
            self.assertEqual(response.status_code, 400, gone)
        self.assertEqual(ContactRequest.objects.count(), 0)

    def test_email_and_mobile_are_checked_and_normalised_like_registration(self) -> None:
        self.assertEqual(self.send(email='not-an-email').status_code, 400)
        self.assertEqual(self.send(email=Ellipsis, mobile_number='12345').status_code, 400)
        self.assertEqual(self.send(email=Ellipsis, mobile_number='abcdefghij').status_code, 400)
        self.assertEqual(self.send(email='  Asha@Example.COM ').status_code, 200)
        self.assertEqual(self.send(email=Ellipsis, mobile_number='+91 98765-43210').status_code, 200)
        first, second = ContactRequest.objects.order_by('pk')
        self.assertEqual((first.guest_email, first.guest_mobile), ('asha@example.com', ''))
        self.assertEqual((second.guest_email, second.guest_mobile), ('', '+919876543210'))

    def test_unknown_and_missing_category_are_refused(self) -> None:
        self.assertEqual(self.send(category_id=999999).status_code, 400)
        self.assertEqual(self.send(category_id=Ellipsis).status_code, 400)
        self.assertEqual(self.send(category_id=0).status_code, 400)
        self.assertEqual(ContactRequest.objects.count(), 0)

    def test_length_limits(self) -> None:
        for bad in ({'description': 'x' * 9}, {'description': 'x' * 5001}, {'full_name': 'n' * 151}, {'subject': 's' * 201}, {'email': 'a' * 250 + '@e.co'}):
            self.assertEqual(self.send(**bad).status_code, 400, list(bad))
        cache.clear()
        self.assertEqual(self.send(description='x' * 5000, full_name='n' * 150, subject='s' * 200).status_code, 200)

    def test_html_is_refused_in_every_text_field_but_plain_symbols_are_fine(self) -> None:
        for field, value in (('description', 'Look <script>alert(1)</script> at this text please'), ('full_name', '<b>Asha</b>'),
                             ('subject', '<img src=x onerror=alert(1)>'), ('description', 'text </div> that is long enough'),
                             ('description', 'comment <!-- hidden --> in a long enough text')):
            self.assertEqual(self.send(**{field: value}).status_code, 400, (field, value))
        self.assertEqual(ContactRequest.objects.count(), 0)
        cache.clear()
        self.assertEqual(self.send(description='My income is < 5000 and my age is > 60, am I eligible?').status_code, 200)

    def test_the_honeypot_gets_the_normal_answer_and_stores_nothing(self) -> None:
        real = self.send()
        cache.clear()
        before = ContactRequest.objects.count()
        trapped = self.send(website='http://spam.example')
        self.assertEqual(trapped.status_code, 200)
        self.assertEqual(trapped.data, real.data)
        self.assertEqual(ContactRequest.objects.count(), before)

    def test_the_view_alone_also_refuses_a_hidden_topic(self) -> None:
        """The topic can be switched off between the form check and the save; the view must not store it then."""
        hidden = ContactCategory.objects.get(name='Technical issue')
        params = CreatePublicRequestRequest(category_id=hidden.category_id, full_name='Asha', description=QUERY, email='a@example.com')
        response = ContactPublicView().create_extract(params=params)
        self.assertGreaterEqual(response.status_code, 400)
        self.assertEqual(ContactRequest.objects.count(), 0)

    def test_the_form_is_throttled_per_ip(self) -> None:
        codes = [self.send().status_code for _ in range(7)]
        self.assertEqual(codes, [200] * 5 + [429] * 2)
        self.assertEqual(ContactRequest.objects.count(), 5)
        cache.clear()
        self.assertEqual(self.send().status_code, 200)

    def test_the_throttle_counts_a_bot_that_trips_the_honeypot_too(self) -> None:
        codes = [self.send(website='x').status_code for _ in range(6)]
        self.assertEqual(codes, [200] * 5 + [429])

    def test_attachments_and_internal_fields_cannot_be_set(self) -> None:
        member = self.member()
        response = self.send(attachment_ids=[1, 2], user_id=member.user_id, status='resolved', admin_reply='Done', priority='high', replied_by=member.user_id)
        self.assertEqual(response.status_code, 200)
        item = ContactRequest.objects.get()
        self.assertEqual((item.user_id, item.status, item.admin_reply, item.priority, item.replied_by_id), (None, 'open', '', 'normal', None))
        self.assertEqual(item.attachments.count(), 0)
        upload = APIClient().post(CREATE, {'category_id': self.topic['Membership'].category_id, 'full_name': 'Asha', 'email': 'a@example.com',
                                           'description': QUERY, 'file': StringIO('x')}, format='multipart')
        self.assertEqual(upload.status_code, 200)
        self.assertEqual(ContactRequest.objects.get(pk__gt=item.pk).attachments.count(), 0)

    def test_a_stale_login_token_does_not_block_a_visitor(self) -> None:
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Bearer not.a.real.token')
        self.assertEqual(self.send(client).status_code, 200)
        self.assertEqual(client.get(CATEGORIES).status_code, 200)

    def test_the_database_refuses_a_request_with_nobody_to_contact(self) -> None:
        category = self.topic['Membership']
        for kwargs in ({}, {'guest_name': 'Only a name'}, {'guest_email': 'a@example.com'}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                ContactRequest.objects.create(user=None, category=category, description='x' * 12, **kwargs)


class GuestCannotReadBackTests(PublicBase):
    def test_there_is_no_public_way_to_read_a_request(self) -> None:
        self.send()
        for url in ('/contact/request/get/?request_id=1', '/contact/request/get_all/', CREATE):
            self.assertIn(APIClient().get(url).status_code, (404, 405), url)
        self.assertEqual(APIClient().post('/contact/category/get_all/').status_code, 405)

    def test_the_member_endpoints_still_need_a_member_login(self) -> None:
        self.send()
        guest = APIClient()
        for url in ('/contact_admin/request/get_all/', '/contact_admin/request/get/?request_id=1', '/contact_admin/category/get_all/'):
            self.assertEqual(guest.get(url).status_code, 401, url)
        self.assertEqual(guest.post('/contact_admin/request/create/', {}, format='json').status_code, 401)

    def test_a_member_never_sees_a_guest_request(self) -> None:
        self.send()
        guest_item = ContactRequest.objects.get()
        member_client = APIClient()
        member_client.force_authenticate(self.member())
        self.assertEqual(member_client.get('/contact_admin/request/get_all/').data['data']['data'], [])
        self.assertEqual(member_client.get(f'/contact_admin/request/get/?request_id={guest_item.pk}').status_code, 404)


class MemberFlowStillWorksTests(PublicBase):
    def test_the_old_member_payload_and_rules_are_unchanged(self) -> None:
        member = self.member()
        client = APIClient()
        client.force_authenticate(member)
        old = {'category_id': self.topic['Membership'].category_id, 'subject': 'Update my address', 'description': QUERY}
        response = client.post('/contact_admin/request/create/', old, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data']['subject'], 'Update my address')
        self.assertEqual(ContactRequest.objects.get().user_id, member.user_id)
        self.assertEqual(client.post('/contact_admin/request/create/', {**old, 'subject': ''}, format='json').status_code, 400)   # members still give a subject
        self.assertEqual(client.post('/contact_admin/request/create/', {k: v for k, v in old.items() if k != 'subject'}, format='json').status_code, 400)
        self.assertEqual(len(client.get('/contact_admin/request/get_all/').data['data']['data']), 1)

    def test_a_member_reply_still_notifies_but_a_guest_reply_sends_nothing(self) -> None:
        member = self.member()
        owned = ContactRequest.objects.create(user=member, category=self.topic['Membership'], subject='Mine', description=QUERY)
        self.send()
        guest_item = ContactRequest.objects.get(user__isnull=True)
        admin = self.staff('Support Handlers')
        ContactRequest.respond(owned.pk, admin, 'resolved', 'Done for you')
        self.assertEqual(Notification.objects.filter(user=member).count(), 1)
        before = Notification.objects.count()
        answered = ContactRequest.respond(guest_item.pk, admin, 'resolved', 'We called you back')
        self.assertEqual((answered.status, answered.admin_reply, answered.replied_by_id), ('resolved', 'We called you back', admin.pk))
        self.assertEqual(Notification.objects.count(), before)


class GuestInAdminTests(PublicBase):
    def setUp(self) -> None:
        super().setUp()
        self.send(full_name='Asha Verma', email='asha@example.com', mobile_number='+919876543210', category_id=self.topic['Complaints'].category_id)
        self.item = ContactRequest.objects.get()
        self.handler = self.staff('Support Handlers')
        self.web = Client()
        self.web.force_login(self.handler)

    def test_a_guest_request_is_in_the_same_admin_list(self) -> None:
        member = self.member()
        ContactRequest.objects.create(user=member, category=self.topic['Membership'], subject='Member one', description=QUERY)
        page = self.web.get('/admin/contact_admin/contactrequest/')
        self.assertContains(page, 'Guest: Asha Verma')
        self.assertContains(page, '(no subject)')
        self.assertContains(page, 'Member one')
        guests_only = self.web.get('/admin/contact_admin/contactrequest/?sender=guest')
        self.assertContains(guests_only, 'Guest: Asha Verma')
        self.assertNotContains(guests_only, 'Member one')
        members_only = self.web.get('/admin/contact_admin/contactrequest/?sender=member')
        self.assertNotContains(members_only, 'Guest: Asha Verma')

    def test_the_admin_can_search_a_guest_by_name_email_or_mobile(self) -> None:
        for term in ('Asha', 'asha@example.com', '9876543210'):
            self.assertContains(self.web.get(f'/admin/contact_admin/contactrequest/?q={term}'), 'Guest: Asha Verma', msg_prefix=term)
        self.assertNotContains(self.web.get('/admin/contact_admin/contactrequest/?q=nobody-here'), 'Guest: Asha Verma')

    def test_the_change_page_shows_how_to_reach_the_guest_and_a_reply_is_stored(self) -> None:
        url = f'/admin/contact_admin/contactrequest/{self.item.pk}/change/'
        page = self.web.get(url)
        self.assertEqual(page.status_code, 200)
        for shown in ('Asha Verma', 'asha@example.com', '+919876543210', 'Complaints'):
            self.assertContains(page, shown)
        saved = self.web.post(url, {'status': 'resolved', 'admin_reply': 'We called you back'})
        self.assertEqual(saved.status_code, 302, getattr(saved, 'context', None) and saved.context['adminform'].form.errors)
        self.item.refresh_from_db()
        self.assertEqual((self.item.status, self.item.admin_reply), ('resolved', 'We called you back'))
        self.assertEqual(Notification.objects.count(), 0)

    def test_other_staff_without_the_support_group_cannot_open_guest_requests(self) -> None:
        outsider = self.staff('Content Editors')
        client = Client()
        client.force_login(outsider)
        self.assertEqual(client.get(f'/admin/contact_admin/contactrequest/{self.item.pk}/change/').status_code, 403)
        self.assertEqual(client.get('/admin/contact_admin/contactrequest/').status_code, 403)
