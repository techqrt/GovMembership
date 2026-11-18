from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from gmp.config import Configurations
from gmp_apps.authentication.models import User
from gmp_apps.contact_admin.models import ContactCategory, ContactRequest
from gmp_apps.membership.models import PermanentApplication, Referral
from gmp_apps.membership.models.referral import ReferralStatus
from gmp_apps.notifications.models import Notification

PASSWORD = 'Sunrise#Valley42'
FAST_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
REASON = 'I have contributed to the organisation for two years.'


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class NotificationBase(APITestCase):
    def setUp(self) -> None:
        cache.clear()
        call_command('setup_admin_groups', stdout=StringIO())
        self.counter = 0

    def member(self, level: str = 'general', **extra) -> User:
        self.counter += 1
        return User.objects.create_user(full_name=f'Member Number{self.counter}', password=PASSWORD, email=f'm{self.counter}@example.com',
                                        email_verified=True, membership_level=level, **extra)

    def admin(self) -> User:
        self.counter += 1
        return User.objects.create_user(full_name='Admin One', password=PASSWORD, email=f'a{self.counter}@example.com', role='admin',
                                        is_staff=True, email_verified=True)

    @staticmethod
    def as_user(user: User | None) -> APIClient:
        client = APIClient()
        if user:
            client.force_authenticate(user)
        return client

    def notify(self, user: User, kind: str = 'support_update', title: str = 'Title', **extra) -> Notification:
        return Notification.send(user.user_id, kind, title, extra.pop('message', 'Message'), **extra)

    def kinds(self, user: User) -> list[str]:
        return list(Notification.objects.filter(user=user).order_by('notification_id').values_list('kind', flat=True))


class NotificationModelTests(NotificationBase):
    def test_send_clips_overlong_text_and_starts_unread(self) -> None:
        user = self.member()
        note = Notification.send(user.user_id, 'support_update', 'T' * 500, 'M' * 900, 'contact_request', 7)
        self.assertEqual((len(note.title), len(note.message), note.is_read, note.reference_id), (200, 500, False, 7))

    def test_mark_read_one_all_and_only_own(self) -> None:
        mine, other = self.member(), self.member()
        first, second, theirs = self.notify(mine), self.notify(mine), self.notify(other)
        self.assertEqual(Notification.mark_read(mine.user_id, first.notification_id), 1)
        self.assertEqual(Notification.unread_count(mine.user_id), 1)
        self.assertEqual(Notification.mark_read(mine.user_id, theirs.notification_id), 0)   # not mine: nothing changes
        self.assertEqual(Notification.mark_read(mine.user_id), 1)
        self.assertEqual((Notification.unread_count(mine.user_id), Notification.unread_count(other.user_id)), (0, 1))
        self.assertEqual(Notification.mark_read(mine.user_id), 0)
        self.assertIsNotNone(Notification.objects.get(pk=second.pk).read_date_time)


class NotificationApiTests(NotificationBase):
    def test_list_is_own_only_newest_first_with_exact_shape(self) -> None:
        mine, other = self.member(), self.member()
        old = self.notify(mine, title='Old')
        Notification.objects.filter(pk=old.pk).update(created_date_time=timezone.now() - timedelta(days=1))
        self.notify(mine, title='New', reference_type='contact_request', reference_id=3)
        self.notify(other, title='Not mine')
        response = self.as_user(mine).get('/notifications/get_all/')
        rows = response.data['data']['data']
        self.assertEqual([r['title'] for r in rows], ['New', 'Old'])
        self.assertEqual(set(rows[0]), {'notificationId', 'kind', 'title', 'message', 'referenceType', 'referenceId', 'isRead', 'createdDateTime', 'readDateTime'})
        self.assertNotIn('Not mine', str(response.data))
        self.assertNotIn('user', ' '.join(rows[0]))

    def test_filters_search_sort_pagination_values(self) -> None:
        member = self.member()
        for index in range(5):
            self.notify(member, kind='referral_verified' if index % 2 else 'support_update', title=f'Note {index}', message=f'about topic {index}')
        Notification.mark_read(member.user_id, Notification.objects.filter(user=member).first().notification_id)
        client = self.as_user(member)
        self.assertEqual(len(client.get('/notifications/get_all/?filter_key=isRead&filter_value=false').data['data']['data']), 4)
        self.assertEqual(len(client.get('/notifications/get_all/?filter_key=isRead&filter_value=true').data['data']['data']), 1)
        self.assertEqual(len(client.get('/notifications/get_all/?filter_key=isRead&filter_value=0').data['data']['data']), 4)
        self.assertEqual(len(client.get('/notifications/get_all/?filter_key=kind&filter_value=referral_verified').data['data']['data']), 2)
        self.assertEqual(len(client.get('/notifications/get_all/?search_key=topic 3').data['data']['data']), 1)
        asc = client.get('/notifications/get_all/?sort_by=notificationId&sort_order=asc').data['data']['data']
        self.assertLess(asc[0]['notificationId'], asc[1]['notificationId'])
        page = client.get('/notifications/get_all/?limit=2').data['data']
        self.assertEqual((len(page['data']), page['totalPage']), (2, 3))
        self.assertEqual(set(client.get('/notifications/get_all/?values=notificationId,title').data['data']['data'][0]), {'notificationId', 'title'})
        for bad in ('filter_key=isRead&filter_value=maybe', 'filter_key=userId&filter_value=1', 'sort_by=user', 'page_num=9'):
            self.assertEqual(client.get(f'/notifications/get_all/?{bad}').status_code, 400, bad)

    def test_unread_count(self) -> None:
        member = self.member()
        self.assertEqual(self.as_user(member).get('/notifications/unread_count/').data['data'], {'unreadCount': 0})
        self.notify(member)
        self.notify(member)
        self.notify(self.member())
        self.assertEqual(self.as_user(member).get('/notifications/unread_count/').data['data'], {'unreadCount': 2})

    def test_mark_one_then_all(self) -> None:
        member = self.member()
        first, _ = self.notify(member), self.notify(member)
        client = self.as_user(member)
        one = client.put('/notifications/mark_read/', {'notification_id': first.notification_id}, format='json')
        self.assertEqual(one.data['data'], {'markedCount': 1, 'unreadCount': 1})
        again = client.put('/notifications/mark_read/', {'notification_id': first.notification_id}, format='json')
        self.assertEqual(again.data['data'], {'markedCount': 0, 'unreadCount': 1})   # idempotent
        everything = client.put('/notifications/mark_read/', {'mark_all': True}, format='json')
        self.assertEqual(everything.data['data'], {'markedCount': 1, 'unreadCount': 0})

    def test_mark_read_validation_and_idor(self) -> None:
        mine, other = self.member(), self.member()
        theirs = self.notify(other)
        client = self.as_user(mine)
        self.assertEqual(client.put('/notifications/mark_read/', {}, format='json').status_code, 400)
        self.assertEqual(client.put('/notifications/mark_read/', {'notification_id': 1, 'mark_all': True}, format='json').status_code, 400)
        self.assertEqual(client.put('/notifications/mark_read/', {'notification_id': 'x'}, format='json').status_code, 400)
        self.assertEqual(client.put('/notifications/mark_read/', {'notification_id': theirs.notification_id}, format='json').status_code, 404)
        self.assertEqual(client.put('/notifications/mark_read/', {'notification_id': 999999}, format='json').status_code, 404)
        self.assertFalse(Notification.objects.get(pk=theirs.pk).is_read)
        client.put('/notifications/mark_read/', {'mark_all': True}, format='json')
        self.assertFalse(Notification.objects.get(pk=theirs.pk).is_read)   # "all" means all of MY notifications

    def test_authentication_and_roles(self) -> None:
        note = self.notify(self.member())
        calls = (('get', '/notifications/get_all/', None), ('get', '/notifications/unread_count/', None),
                 ('put', '/notifications/mark_read/', {'notification_id': note.notification_id}))
        for method, path, body in calls:
            self.assertEqual(getattr(self.as_user(None), method)(path, *( [body] if body else []), **({'format': 'json'} if body else {})).status_code, 401, path)
            self.assertEqual(getattr(self.as_user(self.admin()), method)(path, *( [body] if body else []), **({'format': 'json'} if body else {})).status_code, 403, path)

    def test_a_suspended_member_loses_access(self) -> None:
        member = self.member()
        token = APIClient().post('/auth/login/', {'identifier': member.email, 'password': PASSWORD}, format='json').data['data']['access']
        self.assertEqual(APIClient().get('/notifications/get_all/', HTTP_AUTHORIZATION=f'Bearer {token}').status_code, 200)
        User.objects.filter(pk=member.pk).update(is_active=False)
        self.assertEqual(APIClient().get('/notifications/get_all/', HTTP_AUTHORIZATION=f'Bearer {token}').status_code, 401)

    def test_the_list_costs_a_fixed_number_of_queries(self) -> None:
        member = self.member()
        for _ in range(8):
            self.notify(member)
        client = self.as_user(member)
        with self.assertNumQueries(2):  # count + one page
            client.get('/notifications/get_all/')


class NotificationEventTests(NotificationBase):
    def referral(self, referrer: User, referred: User | None = None, status: str = 'pending') -> Referral:
        return Referral.objects.create(referrer=referrer, referred=referred or self.member(), status=status)

    def test_a_verified_referral_notifies_only_the_referrer_without_naming_anyone(self) -> None:
        referrer, referred, bystander = self.member(), self.member(), self.member()
        referral = self.referral(referrer, referred)
        Referral.on_user_verified(referred)
        note = Notification.objects.get()
        self.assertEqual((note.user_id, note.kind, note.reference_type, note.reference_id), (referrer.user_id, 'referral_verified', 'referral', referral.referral_id))
        self.assertEqual(note.message, f'1 of {Configurations.active_referrals_required} verified referrals so far.')
        for private in (referred.full_name, referred.email, referred.membership_id):
            self.assertNotIn(private, note.title + note.message)
        self.assertFalse(Notification.objects.filter(user__in=[referred, bystander]).exists())

    def test_nothing_is_sent_for_pending_or_already_verified_referrals(self) -> None:
        referrer, referred = self.member(), self.member()
        self.referral(referrer, referred)
        Referral.on_user_verified(referred)
        Referral.on_user_verified(referred)   # second verification event: the referral is no longer pending
        self.assertEqual(Notification.objects.count(), 1)

    def test_the_fifth_referral_also_announces_the_new_level(self) -> None:
        referrer = self.member()
        for _ in range(4):
            referred = self.member()
            self.referral(referrer, referred)
            Referral.on_user_verified(referred)
        self.assertEqual(self.kinds(referrer), ['referral_verified'] * 4)
        fifth = self.member()
        self.referral(referrer, fifth)
        Referral.on_user_verified(fifth)
        self.assertEqual(self.kinds(referrer)[-2:], ['referral_verified', 'level_changed'])
        level = Notification.objects.filter(kind='level_changed').get()
        self.assertIn('Active', level.title)
        referrer.refresh_from_db()
        self.assertEqual(referrer.membership_level, 'active')

    def test_no_level_message_for_members_who_do_not_change_level(self) -> None:
        for level in ('active', 'permanent'):
            member = self.member(level)
            self.assertFalse(Referral.promote_if_eligible(member.user_id))
        self.assertFalse(Notification.objects.exists())

    def test_admin_approval_of_a_flagged_referral_notifies_the_referrer(self) -> None:
        referrer, referred, admin = self.member(), self.member(), self.admin()
        referral = self.referral(referrer, referred, status=ReferralStatus.FLAGGED)
        Referral.review(referral.referral_id, admin, 'approve', '')
        self.assertEqual(self.kinds(referrer), ['referral_verified'])

    def test_rejecting_a_flagged_referral_sends_nothing(self) -> None:
        referrer, admin = self.member(), self.admin()
        referral = self.referral(referrer, status=ReferralStatus.FLAGGED)
        Referral.review(referral.referral_id, admin, 'reject', 'duplicate household')
        self.assertFalse(Notification.objects.exists())

    def test_application_decisions_notify_the_applicant_only(self) -> None:
        admin, approved, rejected, bystander = self.admin(), self.member('active'), self.member('active'), self.member('active')
        yes = PermanentApplication.objects.create(user=approved, reason=REASON)
        no = PermanentApplication.objects.create(user=rejected, reason=REASON)
        PermanentApplication.review(yes.application_id, admin, 'approve')
        PermanentApplication.review(no.application_id, admin, 'reject', 'Please add more history')
        good, bad = Notification.objects.get(user=approved), Notification.objects.get(user=rejected)
        self.assertEqual((good.kind, good.reference_type, good.reference_id), ('application_decided', 'permanent_application', yes.application_id))
        self.assertIn('approved', good.title)
        self.assertIn('Permanent member', good.message)
        self.assertIn('not approved', bad.title)
        self.assertNotIn('Please add more history', bad.title + bad.message)   # remarks are read on the application, not copied around
        self.assertFalse(Notification.objects.filter(user=bystander).exists())
        self.assertFalse(Notification.objects.filter(user=admin).exists())

    def test_a_failed_review_sends_nothing(self) -> None:
        admin, member = self.admin(), self.member('active')
        application = PermanentApplication.objects.create(user=member, reason=REASON)
        with self.assertRaises(ValueError):
            PermanentApplication.review(application.application_id, admin, 'reject', '  ')
        self.assertFalse(Notification.objects.exists())

    def request(self, member: User, subject: str = 'Update my address') -> ContactRequest:
        return ContactRequest.objects.create(user=member, category=ContactCategory.objects.first(), subject=subject, description=REASON)

    def test_support_replies_and_status_changes_notify_the_requester(self) -> None:
        admin, member, other = self.admin(), self.member(), self.member()
        item = self.request(member)
        ContactRequest.respond(item.pk, admin, 'in_progress', 'We are on it')
        ContactRequest.respond(item.pk, admin, 'in_progress', 'We are on it')   # nothing changed
        ContactRequest.respond(item.pk, admin, 'resolved', 'We are on it')      # status only
        ContactRequest.respond(item.pk, admin, 'resolved', 'Done, see profile page')   # reply text only
        notes = list(Notification.objects.filter(user=member).order_by('notification_id'))
        self.assertEqual(len(notes), 3)
        self.assertEqual({n.kind for n in notes}, {'support_update'})
        self.assertIn('in progress', notes[0].message)
        self.assertIn('The administration replied.', notes[0].message)
        self.assertIn('resolved', notes[1].message)
        self.assertNotIn('The administration replied.', notes[1].message)
        self.assertTrue(all(n.reference_id == item.request_id for n in notes))
        self.assertFalse(Notification.objects.filter(user__in=[other, admin]).exists())

    def test_reply_text_and_admin_identity_are_not_copied_into_the_notification(self) -> None:
        admin, member = self.admin(), self.member()
        item = self.request(member, subject='S' * 200)
        ContactRequest.respond(item.pk, admin, 'resolved', 'A confidential-looking reply')
        note = Notification.objects.get()
        text = note.title + note.message
        for private in ('confidential-looking', admin.full_name, admin.email):
            self.assertNotIn(private, text)
        self.assertLessEqual(len(note.message), 500)

    def test_the_whole_flow_through_the_api_reaches_the_member_dashboard_list(self) -> None:
        member = self.member()
        item = self.request(member)
        ContactRequest.respond(item.pk, self.admin(), 'resolved', 'Done')
        rows = self.as_user(member).get('/notifications/get_all/').data['data']['data']
        self.assertEqual((len(rows), rows[0]['kind'], rows[0]['isRead']), (1, 'support_update', False))
        with mock.patch.object(Notification, 'send', side_effect=AssertionError('no extra sends')):
            self.as_user(member).get('/notifications/get_all/')   # reading never creates notifications
