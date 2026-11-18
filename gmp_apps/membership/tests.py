from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.conf import settings
from django.test import Client, override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from gmp.config import Configurations
from gmp_apps.authentication.models import User
from gmp_apps.authentication.otp_delivery import LocMemOtpBackend
from gmp_apps.common.exceptions.errors import NotFoundError
from gmp_apps.membership.models import PermanentApplication, Referral, ReferralInvite
from gmp_apps.membership.models.referral import ReferralStatus
from gmp_apps.membership.tasks import expire_referral_invites

PASSWORD = 'Sunrise#Valley42'
LOCMEM = 'gmp_apps.authentication.otp_delivery.LocMemOtpBackend'
FAST_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
REASON = 'I have contributed to the organisation for two years.'


@override_settings(OTP_DELIVERY_BACKEND=LOCMEM, PASSWORD_HASHERS=FAST_HASHERS)
class MembershipBaseTestCase(APITestCase):
    def setUp(self) -> None:
        cache.clear()
        LocMemOtpBackend.outbox.clear()
        patcher = mock.patch.object(Configurations, 'referral_flag_same_ip', False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.counter = 0

    # ---------- builders ----------

    def make_member(self, level: str = 'general', verified: bool = True, **extra) -> User:
        self.counter += 1
        return User.objects.create_user(
            full_name=f'Member Number{self.counter}', password=PASSWORD,
            email=f'member{self.counter}@example.com', membership_level=level,
            email_verified=verified, **extra,
        )

    def make_admin(self) -> User:
        self.counter += 1
        return User.objects.create_user(
            full_name='Admin One', password=PASSWORD, email=f'admin{self.counter}@example.com',
            role='admin', email_verified=True,
        )

    def as_user(self, user: User | None) -> APIClient:
        client = APIClient()
        if user:
            client.force_authenticate(user)
        return client

    def register_referred(self, code: str, email: str | None = None, ip: str = '10.0.0.9', verify: bool = True) -> User:
        email = email or f'ref{self.counter}@example.com'
        self.counter += 1
        response = APIClient().post(
            '/auth/register/',
            {'full_name': 'Ref Person', 'email': email, 'password': PASSWORD, 'referral_code': code},
            format='json', REMOTE_ADDR=ip,
        )
        self.assertEqual(response.status_code, 200, response.data)
        if verify:
            otp = [m for m in LocMemOtpBackend.outbox if m['destination'] == email][-1]['code']
            verified = APIClient().post('/auth/verify_otp/', {'identifier': email, 'otp': otp}, format='json')
            self.assertEqual(verified.status_code, 200, verified.data)
        return User.objects.get(email=email)

    def verified_referral(self, referrer: User) -> Referral:
        referred = self.make_member()
        return Referral.objects.create(
            referrer=referrer, referred=referred, status=ReferralStatus.VERIFIED, verified_date_time=timezone.now(),
        )

    def level(self, user: User) -> str:
        user.refresh_from_db()
        return user.membership_level


class ReferralRegistrationTests(MembershipBaseTestCase):
    def test_register_with_code_creates_pending_referral_not_counted(self) -> None:
        referrer = self.make_member()
        referred = self.register_referred(referrer.referral_code, verify=False)
        referral = Referral.objects.get(referred=referred)
        self.assertEqual((referral.referrer_id, referral.status), (referrer.user_id, 'pending'))
        self.assertEqual(Referral.verified_count(referrer.user_id), 0)

    def test_verification_makes_referral_verified(self) -> None:
        referrer = self.make_member()
        referred = self.register_referred(referrer.referral_code)
        self.assertEqual(Referral.objects.get(referred=referred).status, 'verified')
        self.assertEqual(Referral.verified_count(referrer.user_id), 1)

    def test_invalid_or_unusable_code_rejected_and_no_account_created(self) -> None:
        unverified = self.make_member(verified=False)
        suspended = self.make_member(is_active=False)
        for code in ('NOPE1234', unverified.referral_code, suspended.referral_code):
            response = APIClient().post(
                '/auth/register/',
                {'full_name': 'X Y', 'email': f'x{code}@example.com', 'password': PASSWORD, 'referral_code': code},
                format='json',
            )
            self.assertEqual(response.status_code, 400, code)
        self.assertEqual(Referral.objects.count(), 0)
        self.assertFalse(User.objects.filter(email__startswith='x').exists())

    def test_registration_without_code_has_no_referral(self) -> None:
        APIClient().post('/auth/register/', {'full_name': 'A B', 'email': 'a@example.com', 'password': PASSWORD}, format='json')
        self.assertEqual(Referral.objects.count(), 0)

    def test_code_is_case_insensitive(self) -> None:
        referrer = self.make_member()
        self.register_referred(referrer.referral_code.lower(), verify=False)
        self.assertEqual(Referral.objects.count(), 1)


class PromotionTests(MembershipBaseTestCase):
    def test_four_verified_stays_general_fifth_makes_active(self) -> None:
        referrer = self.make_member()
        for index in range(4):
            self.register_referred(referrer.referral_code, email=f'r{index}@example.com')
        self.assertEqual(self.level(referrer), 'general')
        self.register_referred(referrer.referral_code, email='r4@example.com')
        self.assertEqual(self.level(referrer), 'active')

    def test_unverified_registrations_do_not_count(self) -> None:
        referrer = self.make_member()
        for index in range(4):
            self.register_referred(referrer.referral_code, email=f'v{index}@example.com')
        for index in range(3):
            self.register_referred(referrer.referral_code, email=f'u{index}@example.com', verify=False)
        self.assertEqual(self.level(referrer), 'general')

    def test_suspended_referred_member_does_not_qualify(self) -> None:
        referrer = self.make_member()
        for _ in range(4):
            self.verified_referral(referrer)
        extra = self.verified_referral(referrer)
        User.objects.filter(pk=extra.referred_id).update(is_active=False)
        self.assertFalse(Referral.promote_if_eligible(referrer.user_id))
        self.assertEqual(self.level(referrer), 'general')

    def test_progress_endpoint_and_link_clicks_grant_nothing(self) -> None:
        referrer = self.make_member()
        client = self.as_user(referrer)
        for _ in range(3):
            client.get(f'/membership/progress/get/?ref={referrer.referral_code}')
        self.assertEqual(self.level(referrer), 'general')

    def test_permanent_is_never_touched_by_referral_promotion(self) -> None:
        permanent = self.make_member(level='permanent')
        for _ in range(6):
            self.verified_referral(permanent)
        self.assertFalse(Referral.promote_if_eligible(permanent.user_id))
        self.assertEqual(self.level(permanent), 'permanent')

    def test_active_never_becomes_permanent_automatically(self) -> None:
        referrer = self.make_member()
        for index in range(8):
            self.register_referred(referrer.referral_code, email=f'm{index}@example.com')
        self.assertEqual(self.level(referrer), 'active')

    def test_threshold_is_configurable(self) -> None:
        referrer = self.make_member()
        with mock.patch.object(Configurations, 'active_referrals_required', 2):
            for index in range(2):
                self.register_referred(referrer.referral_code, email=f't{index}@example.com')
        self.assertEqual(self.level(referrer), 'active')


class FraudCheckTests(MembershipBaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.object(Configurations, 'referral_flag_same_ip', True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_same_ip_as_referrer_is_flagged_and_never_counts(self) -> None:
        referrer = self.make_member(registration_ip='10.0.0.1')
        referred = self.register_referred(referrer.referral_code, ip='10.0.0.1')
        referral = Referral.objects.get(referred=referred)
        self.assertEqual(referral.status, 'flagged')
        self.assertIn('same IP', referral.flag_reason)
        self.assertEqual(Referral.verified_count(referrer.user_id), 0)

    def test_two_referrals_from_one_ip_second_is_flagged(self) -> None:
        referrer = self.make_member(registration_ip='10.0.0.1')
        first = self.register_referred(referrer.referral_code, email='one@example.com', ip='10.0.0.7')
        second = self.register_referred(referrer.referral_code, email='two@example.com', ip='10.0.0.7')
        self.assertEqual(Referral.objects.get(referred=first).status, 'verified')
        self.assertEqual(Referral.objects.get(referred=second).status, 'flagged')

    def test_velocity_limit_flags_excess_referrals(self) -> None:
        referrer = self.make_member(registration_ip='10.0.0.1')
        with mock.patch.object(Configurations, 'referral_max_per_day', 2):
            for index in range(3):
                self.register_referred(referrer.referral_code, email=f'q{index}@example.com', ip=f'10.0.1.{index}')
        statuses = list(Referral.objects.order_by('referral_id').values_list('status', flat=True))
        self.assertEqual(statuses, ['verified', 'verified', 'flagged'])

    def test_person_can_only_be_referred_once(self) -> None:
        first, second, referred = self.make_member(), self.make_member(), self.make_member()
        Referral.objects.create(referrer=first, referred=referred)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Referral.objects.create(referrer=second, referred=referred)

    def test_self_referral_rejected(self) -> None:
        member = self.make_member()
        with self.assertRaises(ValueError):
            Referral.attach(referrer_code=member.referral_code, referred=member)

    def test_duplicate_contact_cannot_register_again(self) -> None:
        referrer = self.make_member()
        self.register_referred(referrer.referral_code, email='dup@example.com')
        again = APIClient().post(
            '/auth/register/',
            {'full_name': 'D D', 'email': 'dup@example.com', 'password': PASSWORD, 'referral_code': referrer.referral_code},
            format='json',
        )
        self.assertEqual(again.status_code, 400)
        self.assertEqual(Referral.objects.count(), 1)


class MemberReferralListTests(MembershipBaseTestCase):
    def test_only_own_referrals_with_no_contact_details(self) -> None:
        mine, other = self.make_member(), self.make_member()
        self.verified_referral(mine)
        self.verified_referral(other)
        response = self.as_user(mine).get('/membership/referral/get_all/')
        rows = response.data['data']['data']
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0]), {'referralId', 'referredFirstName', 'status', 'createdDateTime', 'verifiedDateTime'})
        self.assertNotIn('@', str(response.data))

    def test_pagination_at_queryset_level(self) -> None:
        member = self.make_member()
        for _ in range(5):
            self.verified_referral(member)
        client = self.as_user(member)
        first = client.get('/membership/referral/get_all/?limit=2&page_num=1').data['data']
        last = client.get('/membership/referral/get_all/?limit=2&page_num=3').data['data']
        self.assertEqual((len(first['data']), first['totalPage'], first['presentPage']), (2, 3, 1))
        self.assertIn('page_num=2', first['nextPageUrl'])
        self.assertNotIn('nextPageUrl', last)
        self.assertEqual(len(last['data']), 1)
        self.assertIn('previousPageUrl', last)
        with self.assertNumQueries(2):
            client.get('/membership/referral/get_all/?limit=2&page_num=1')

    def test_page_beyond_range_and_bad_params(self) -> None:
        member = self.make_member()
        client = self.as_user(member)
        self.assertEqual(client.get('/membership/referral/get_all/?page_num=9').status_code, 400)
        self.assertEqual(client.get('/membership/referral/get_all/?limit=101').status_code, 400)
        self.assertEqual(client.get('/membership/referral/get_all/?sort_by=password').status_code, 400)
        self.assertEqual(client.get('/membership/referral/get_all/?filter_key=referrer__password&filter_value=x').status_code, 400)
        self.assertEqual(client.get('/membership/referral/get_all/?filter_key=status').status_code, 400)
        self.assertEqual(client.get('/membership/referral/get_all/?from_date=2026-01-01').status_code, 400)

    def test_filter_sort_values_and_dates(self) -> None:
        member = self.make_member()
        self.verified_referral(member)
        Referral.objects.create(referrer=member, referred=self.make_member())
        client = self.as_user(member)
        filtered = client.get('/membership/referral/get_all/?filter_key=status&filter_value=pending').data['data']['data']
        self.assertEqual([r['status'] for r in filtered], ['pending'])
        asc = client.get('/membership/referral/get_all/?sort_by=referralId&sort_order=asc').data['data']['data']
        self.assertLess(asc[0]['referralId'], asc[1]['referralId'])
        values = client.get('/membership/referral/get_all/?values=referralId,status').data['data']['data']
        self.assertEqual(set(values[0]), {'referralId', 'status'})
        today = timezone.localdate().strftime('%d-%m-%y')
        yesterday = (timezone.localdate() - timedelta(days=1)).strftime('%d-%m-%y')
        self.assertEqual(len(client.get(f'/membership/referral/get_all/?from_date={today}&to_date={today}').data['data']['data']), 2)
        self.assertEqual(len(client.get(f'/membership/referral/get_all/?to_date={yesterday}').data['data']['data']), 0)

    def test_anonymous_and_admin_blocked(self) -> None:
        self.assertEqual(self.as_user(None).get('/membership/referral/get_all/').status_code, 401)
        self.assertEqual(self.as_user(self.make_admin()).get('/membership/referral/get_all/').status_code, 403)


class ProgressTests(MembershipBaseTestCase):
    def test_progress_values(self) -> None:
        member = self.make_member()
        for _ in range(2):
            self.verified_referral(member)
        Referral.objects.create(referrer=member, referred=self.make_member())
        data = self.as_user(member).get('/membership/progress/get/').data['data']
        self.assertEqual(data['verifiedReferrals'], 2)
        self.assertEqual(data['pendingReferrals'], 1)
        self.assertEqual((data['requiredReferrals'], data['remainingReferrals']), (5, 3))
        self.assertEqual(data['membershipLevel'], 'general')
        self.assertTrue(data['referralLink'].endswith(f'?ref={member.referral_code}'))
        self.assertFalse(data['canApplyForPermanent'])
        self.assertIsNone(data['permanentApplication'])

    def test_progress_is_always_own_and_needs_member_role(self) -> None:
        mine, other = self.make_member(), self.make_member()
        self.verified_referral(other)
        data = self.as_user(mine).get(f'/membership/progress/get/?user_id={other.user_id}').data['data']
        self.assertEqual((data['referralCode'], data['verifiedReferrals']), (mine.referral_code, 0))
        self.assertEqual(self.as_user(None).get('/membership/progress/get/').status_code, 401)
        self.assertEqual(self.as_user(self.make_admin()).get('/membership/progress/get/').status_code, 403)

    def test_active_member_can_apply_flag(self) -> None:
        member = self.make_member(level='active')
        self.assertTrue(self.as_user(member).get('/membership/progress/get/').data['data']['canApplyForPermanent'])


class PermanentApplicationTests(MembershipBaseTestCase):
    def apply(self, user: User | None, reason: str = REASON, **extra):
        return self.as_user(user).post('/membership/permanent_application/create/', {'reason': reason, **extra}, format='json')

    def test_active_member_applies(self) -> None:
        member = self.make_member(level='active')
        response = self.apply(member)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data']['status'], 'pending')
        self.assertEqual(self.level(member), 'active')

    def test_general_and_permanent_cannot_apply(self) -> None:
        self.assertEqual(self.apply(self.make_member()).status_code, 400)
        self.assertEqual(self.apply(self.make_member(level='permanent')).status_code, 400)

    def test_only_one_pending_application(self) -> None:
        member = self.make_member(level='active')
        self.apply(member)
        self.assertEqual(self.apply(member).status_code, 400)
        self.assertEqual(PermanentApplication.objects.count(), 1)

    def test_db_constraint_blocks_second_pending(self) -> None:
        member = self.make_member(level='active')
        PermanentApplication.objects.create(user=member, reason=REASON)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PermanentApplication.objects.create(user=member, reason=REASON)

    def test_validation_and_permissions(self) -> None:
        member = self.make_member(level='active')
        self.assertEqual(self.apply(member, reason='short').status_code, 400)
        self.assertEqual(self.apply(None).status_code, 401)
        self.assertEqual(self.apply(self.make_admin()).status_code, 403)

    def test_application_always_belongs_to_caller(self) -> None:
        member, other = self.make_member(level='active'), self.make_member(level='active')
        self.apply(member, user_id=other.user_id, status='approved')
        application = PermanentApplication.objects.get()
        self.assertEqual((application.user_id, application.status), (member.user_id, 'pending'))
        self.assertEqual(self.level(member), 'active')

    def test_idor_get_other_members_application(self) -> None:
        owner, intruder = self.make_member(level='active'), self.make_member(level='active')
        application = PermanentApplication.objects.create(user=owner, reason=REASON)
        url = f'/membership/permanent_application/get/?application_id={application.application_id}'
        self.assertEqual(self.as_user(owner).get(url).status_code, 200)
        self.assertEqual(self.as_user(intruder).get(url).status_code, 404)
        self.assertEqual(self.as_user(None).get(url).status_code, 401)

    def test_member_list_shows_only_own(self) -> None:
        mine, other = self.make_member(level='active'), self.make_member(level='active')
        PermanentApplication.objects.create(user=mine, reason=REASON, status='rejected')
        PermanentApplication.objects.create(user=other, reason=REASON)
        rows = self.as_user(mine).get('/membership/permanent_application/get_all/').data['data']['data']
        self.assertEqual(len(rows), 1)
        self.assertNotIn('userId', rows[0])
        self.assertNotIn('membershipId', rows[0])

    def test_profile_update_still_cannot_change_level(self) -> None:
        member = self.make_member()
        self.as_user(member).put('/auth/profile/update/', {'city': 'X', 'membership_level': 'permanent'}, format='json')
        self.assertEqual(self.level(member), 'general')


class InviteHelpers:
    URL = '/membership/referral_invite/create/'

    def refer(self, user: User | None, **data):
        payload = {'full_name': 'Neha Shah', 'email': 'neha@example.com'}
        payload.update(data)
        return self.as_user(user).post(self.URL, payload, format='json')

    def register_plain(self, email: str | None = None, mobile: str | None = None, ip: str = '10.0.0.9',
                       code: str | None = None, verify: bool = True) -> User:
        body = {'full_name': 'Invitee Person', 'password': PASSWORD}
        if email:
            body['email'] = email
        if mobile:
            body['mobile_number'] = mobile
        if code:
            body['referral_code'] = code
        response = APIClient().post('/auth/register/', body, format='json', REMOTE_ADDR=ip)
        self.assertEqual(response.status_code, 200, response.data)
        destination = email or mobile
        if verify:
            otp = [m for m in LocMemOtpBackend.outbox if m['destination'] == destination][-1]['code']
            self.assertEqual(APIClient().post('/auth/verify_otp/', {'identifier': destination, 'otp': otp}, format='json').status_code, 200)
        return User.objects.get(email=email) if email else User.objects.get(mobile_number=mobile)


class ReferralInviteTests(InviteHelpers, MembershipBaseTestCase):
    # ---------- create ----------

    def test_member_refers_a_person(self) -> None:
        member = self.make_member()
        response = self.refer(member)
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data['data']
        self.assertEqual((data['status'], data['fullName'], data['email']), ('invited', 'Neha Shah', 'neha@example.com'))
        self.assertTrue(data['referralLink'].endswith(f'?ref={member.referral_code}'))
        invite = ReferralInvite.objects.get()
        self.assertEqual(invite.referrer_id, member.user_id)
        self.assertEqual(self.level(member), 'general')
        self.assertEqual(Referral.objects.count(), 0)

    def test_by_mobile_normalizes_and_validates(self) -> None:
        member = self.make_member()
        self.assertEqual(self.refer(member, email=None, mobile_number='98765 43210').status_code, 200)
        self.assertEqual(ReferralInvite.objects.get().mobile_number, '9876543210')
        self.assertEqual(self.refer(member, email=None, mobile_number='12').status_code, 400)

    def test_validation_errors(self) -> None:
        member = self.make_member()
        self.assertEqual(self.refer(member, email=None).status_code, 400)
        self.assertEqual(self.refer(member, email='not-an-email').status_code, 400)
        self.assertEqual(self.as_user(member).post(self.URL, {'email': 'a@example.com'}, format='json').status_code, 400)
        self.assertEqual(ReferralInvite.objects.count(), 0)

    def test_permissions(self) -> None:
        self.assertEqual(self.refer(None).status_code, 401)
        self.assertEqual(self.refer(self.make_admin()).status_code, 403)
        self.assertEqual(ReferralInvite.objects.count(), 0)

    def test_referrer_is_always_the_caller(self) -> None:
        member, other = self.make_member(), self.make_member()
        self.refer(member, referrer_id=other.user_id, user_id=other.user_id, status='registered')
        invite = ReferralInvite.objects.get()
        self.assertEqual((invite.referrer_id, invite.status), (member.user_id, 'invited'))

    def test_cannot_refer_yourself(self) -> None:
        member = self.make_member()
        self.assertEqual(self.refer(member, email=member.email).status_code, 400)

    def test_cannot_refer_existing_member_or_taken_contact_and_errors_look_identical(self) -> None:
        member, other, existing = self.make_member(), self.make_member(), self.make_member()
        self.refer(other, email='taken@example.com')
        already_member = self.refer(member, email=existing.email)
        already_invited = self.refer(member, email='taken@example.com')
        self.assertEqual((already_member.status_code, already_invited.status_code), (400, 400))
        self.assertEqual(already_member.data, already_invited.data)
        self.assertEqual(ReferralInvite.objects.filter(referrer=member).count(), 0)

    def test_referring_same_person_twice_is_refused(self) -> None:
        member = self.make_member()
        self.refer(member)
        again = self.refer(member)
        self.assertEqual(again.status_code, 400)
        self.assertEqual(ReferralInvite.objects.count(), 1)

    def test_db_allows_only_one_open_invite_per_contact(self) -> None:
        first, second = self.make_member(), self.make_member()
        ReferralInvite.objects.create(referrer=first, full_name='A', email='dup@example.com')
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReferralInvite.objects.create(referrer=second, full_name='B', email='dup@example.com')

    def test_daily_limit(self) -> None:
        member = self.make_member()
        with mock.patch.object(Configurations, 'referral_max_per_day', 2):
            codes = [self.refer(member, email=f'p{i}@example.com').status_code for i in range(3)]
        self.assertEqual(codes, [200, 200, 400])

    # ---------- registration linking ----------

    def test_registering_with_invited_email_links_referral_without_code(self) -> None:
        referrer = self.make_member()
        self.refer(referrer)
        invitee = self.register_plain(email='neha@example.com', verify=False)
        referral = Referral.objects.get(referred=invitee)
        self.assertEqual((referral.referrer_id, referral.status), (referrer.user_id, 'pending'))
        self.assertEqual(ReferralInvite.objects.get().status, 'registered')
        self.assertEqual(Referral.verified_count(referrer.user_id), 0)

    def test_invite_by_mobile_links_on_mobile_registration(self) -> None:
        referrer = self.make_member()
        self.refer(referrer, email=None, mobile_number='9876543210')
        invitee = self.register_plain(mobile='9876543210')
        self.assertEqual(Referral.objects.get(referred=invitee).status, 'verified')

    def test_explicit_code_wins_over_invitation(self) -> None:
        inviter, code_owner = self.make_member(), self.make_member()
        self.refer(inviter)
        invitee = self.register_plain(email='neha@example.com', code=code_owner.referral_code)
        self.assertEqual(Referral.objects.get(referred=invitee).referrer_id, code_owner.user_id)
        self.assertEqual(ReferralInvite.objects.get().status, 'registered')

    def test_unusable_inviter_does_not_block_registration(self) -> None:
        referrer = self.make_member()
        self.refer(referrer)
        User.objects.filter(pk=referrer.pk).update(is_active=False)
        invitee = self.register_plain(email='neha@example.com')
        self.assertTrue(invitee.email_verified)
        self.assertFalse(Referral.objects.filter(referred=invitee).exists())
        self.assertEqual(ReferralInvite.objects.get().status, 'registered')

    def test_unrelated_registration_is_untouched(self) -> None:
        self.refer(self.make_member())
        stranger = self.register_plain(email='stranger@example.com')
        self.assertFalse(Referral.objects.filter(referred=stranger).exists())
        self.assertEqual(ReferralInvite.objects.get().status, 'invited')

    def test_fraud_checks_apply_to_invited_registrations(self) -> None:
        referrer = self.make_member(registration_ip='10.0.0.1')
        self.refer(referrer)
        with mock.patch.object(Configurations, 'referral_flag_same_ip', True):
            invitee = self.register_plain(email='neha@example.com', ip='10.0.0.1')
        self.assertEqual(Referral.objects.get(referred=invitee).status, 'flagged')
        self.assertEqual(Referral.verified_count(referrer.user_id), 0)

    def test_five_invited_people_registering_and_verifying_make_referrer_active(self) -> None:
        referrer = self.make_member()
        for index in range(5):
            self.refer(referrer, full_name=f'Person {index}', email=f'inv{index}@example.com')
        for index in range(4):
            self.register_plain(email=f'inv{index}@example.com')
        self.assertEqual(self.level(referrer), 'general')
        self.register_plain(email='inv4@example.com')
        self.assertEqual(self.level(referrer), 'active')

    def test_inviting_never_promotes_by_itself(self) -> None:
        referrer = self.make_member()
        for index in range(8):
            self.refer(referrer, full_name=f'P{index}', email=f'solo{index}@example.com')
        self.assertEqual(self.level(referrer), 'general')

    # ---------- list ----------

    def test_list_only_own_with_filter_search_pagination(self) -> None:
        mine, other = self.make_member(), self.make_member()
        for index in range(3):
            self.refer(mine, full_name=f'Mine {index}', email=f'mine{index}@example.com')
        self.refer(other, full_name='Theirs', email='theirs@example.com')
        self.register_plain(email='mine0@example.com')
        client = self.as_user(mine)
        rows = client.get('/membership/referral_invite/get_all/').data['data']['data']
        self.assertEqual(len(rows), 3)
        self.assertNotIn('theirs@example.com', str(rows))
        registered = client.get('/membership/referral_invite/get_all/?filter_key=status&filter_value=registered').data['data']['data']
        self.assertEqual([r['email'] for r in registered], ['mine0@example.com'])
        found = client.get('/membership/referral_invite/get_all/?search_key=Mine 2').data['data']['data']
        self.assertEqual(len(found), 1)
        page = client.get('/membership/referral_invite/get_all/?limit=2').data['data']
        self.assertEqual((len(page['data']), page['totalPage']), (2, 2))
        self.assertIn('nextPageUrl', page)
        self.assertEqual(client.get('/membership/referral_invite/get_all/?sort_by=nope').status_code, 400)

    def test_list_permissions(self) -> None:
        self.assertEqual(self.as_user(None).get('/membership/referral_invite/get_all/').status_code, 401)
        self.assertEqual(self.as_user(self.make_admin()).get('/membership/referral_invite/get_all/').status_code, 403)


class ReferralInviteLifecycleTests(InviteHelpers, MembershipBaseTestCase):
    def cancel(self, user: User | None, invite_id: int | str):
        return self.as_user(user).delete(f'/membership/referral_invite/delete/?invite_id={invite_id}')

    def expire(self, invite: ReferralInvite) -> None:
        ReferralInvite.objects.filter(pk=invite.pk).update(expires_at=timezone.now() - timedelta(minutes=1))

    # ---------- cancel ----------

    def test_member_cancels_own_open_referral(self) -> None:
        member = self.make_member()
        invite_id = self.refer(member).data['data']['inviteId']
        response = self.cancel(member, invite_id)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data']['status'], 'cancelled')
        self.assertEqual(ReferralInvite.objects.get().status, 'cancelled')
        self.assertEqual(self.level(member), 'general')

    def test_cancelled_contact_can_be_referred_again_and_old_invite_does_not_link(self) -> None:
        first, second = self.make_member(), self.make_member()
        invite_id = self.refer(first).data['data']['inviteId']
        self.cancel(first, invite_id)
        self.assertEqual(self.refer(second).status_code, 200)
        invitee = self.register_plain(email='neha@example.com')
        self.assertEqual(Referral.objects.get(referred=invitee).referrer_id, second.user_id)

    def test_registering_after_cancel_creates_no_referral(self) -> None:
        member = self.make_member()
        self.cancel(member, self.refer(member).data['data']['inviteId'])
        invitee = self.register_plain(email='neha@example.com')
        self.assertFalse(Referral.objects.filter(referred=invitee).exists())

    def test_cancel_permissions_idor_and_bad_input(self) -> None:
        owner, intruder = self.make_member(), self.make_member()
        invite_id = self.refer(owner).data['data']['inviteId']
        self.assertEqual(self.cancel(None, invite_id).status_code, 401)
        self.assertEqual(self.cancel(self.make_admin(), invite_id).status_code, 403)
        self.assertEqual(self.cancel(intruder, invite_id).status_code, 404)
        self.assertEqual(self.cancel(owner, 999999).status_code, 404)
        self.assertEqual(self.as_user(owner).delete('/membership/referral_invite/delete/').status_code, 400)
        self.assertEqual(ReferralInvite.objects.get().status, 'invited')

    def test_cannot_cancel_registered_cancelled_or_expired(self) -> None:
        member = self.make_member()
        registered = self.refer(member, email='a@example.com').data['data']['inviteId']
        self.register_plain(email='a@example.com')
        cancelled = self.refer(member, email='b@example.com').data['data']['inviteId']
        self.cancel(member, cancelled)
        expired = ReferralInvite.objects.get(pk=self.refer(member, email='c@example.com').data['data']['inviteId'])
        self.expire(expired)
        for invite_id in (registered, cancelled, expired.invite_id):
            self.assertEqual(self.cancel(member, invite_id).status_code, 400, invite_id)
        self.assertEqual(ReferralInvite.objects.get(pk=registered).status, 'registered')

    # ---------- expiry ----------

    def test_invite_gets_expiry_from_ttl_setting(self) -> None:
        member = self.make_member()
        with mock.patch.object(Configurations, 'referral_invite_ttl_days', 3):
            self.refer(member)
        left = ReferralInvite.objects.get().expires_at - timezone.now()
        self.assertLess(abs(left - timedelta(days=3)), timedelta(minutes=1))

    def test_expired_invite_does_not_link_registration(self) -> None:
        member = self.make_member()
        invite = ReferralInvite.objects.get(pk=self.refer(member).data['data']['inviteId'])
        self.expire(invite)
        invitee = self.register_plain(email='neha@example.com')
        self.assertFalse(Referral.objects.filter(referred=invitee).exists())
        self.assertEqual(ReferralInvite.objects.get().status, 'expired')

    def test_expired_contact_can_be_referred_again_by_anyone(self) -> None:
        first, second = self.make_member(), self.make_member()
        self.expire(ReferralInvite.objects.get(pk=self.refer(first).data['data']['inviteId']))
        self.assertEqual(self.refer(second).status_code, 200)
        statuses = sorted(ReferralInvite.objects.values_list('status', flat=True))
        self.assertEqual(statuses, ['expired', 'invited'])

    def test_list_shows_expiry_and_marks_expired(self) -> None:
        member = self.make_member()
        old = ReferralInvite.objects.get(pk=self.refer(member, email='old@example.com').data['data']['inviteId'])
        self.refer(member, email='new@example.com')
        self.expire(old)
        client = self.as_user(member)
        rows = client.get('/membership/referral_invite/get_all/').data['data']['data']
        by_email = {r['email']: r for r in rows}
        self.assertEqual((by_email['old@example.com']['status'], by_email['new@example.com']['status']), ('expired', 'invited'))
        self.assertIn('expiresAt', by_email['new@example.com'])
        only = client.get('/membership/referral_invite/get_all/?filter_key=status&filter_value=expired').data['data']['data']
        self.assertEqual([r['email'] for r in only], ['old@example.com'])

    def test_expired_invite_never_counts_towards_active(self) -> None:
        referrer = self.make_member()
        for index in range(5):
            self.refer(referrer, full_name=f'P{index}', email=f'e{index}@example.com')
        ReferralInvite.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        for index in range(5):
            self.register_plain(email=f'e{index}@example.com')
        self.assertEqual(self.level(referrer), 'general')
        self.assertEqual(Referral.objects.count(), 0)


class ReferralInviteAdminTests(MembershipBaseTestCase):
    """Admin side lives in the Unfold ModelAdmin (Django admin), not in new REST endpoints."""

    CHANGELIST = '/admin/membership/referralinvite/'

    def setUp(self) -> None:
        super().setUp()
        self.staff = User.objects.create_superuser(
            full_name='Super Admin', password=PASSWORD, email='super@example.com',
        )
        self.client = Client()
        self.client.force_login(self.staff)

    def invite(self, email: str, **extra) -> ReferralInvite:
        return ReferralInvite.objects.create(referrer=self.make_member(), full_name='X Y', email=email, **extra)

    def run_action(self, action: str, *invites: ReferralInvite):
        return self.client.post(
            self.CHANGELIST,
            {'action': action, '_selected_action': [i.pk for i in invites]}, follow=True,
        )

    def test_changelist_and_other_admin_pages_render(self) -> None:
        self.invite('a@example.com')
        for path in (self.CHANGELIST, '/admin/membership/referral/', '/admin/membership/permanentapplication/',
                     '/admin/authentication/user/', '/admin/authentication/otp/'):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_cancel_action_cancels_only_open_invites(self) -> None:
        open_invite = self.invite('open@example.com')
        done = self.invite('done@example.com', status='registered')
        response = self.run_action('cancel_invites', open_invite, done)
        self.assertEqual(response.status_code, 200)
        open_invite.refresh_from_db()
        done.refresh_from_db()
        self.assertEqual((open_invite.status, done.status), ('cancelled', 'registered'))

    def test_extend_action_extends_open_but_not_expired(self) -> None:
        soon = timezone.now() + timedelta(days=1)
        open_invite = self.invite('open@example.com', expires_at=soon)
        stale = self.invite('stale@example.com', expires_at=timezone.now() - timedelta(days=1))
        self.run_action('extend_expiry', open_invite, stale)
        open_invite.refresh_from_db()
        stale.refresh_from_db()
        self.assertGreater(open_invite.expires_at, soon + timedelta(days=20))
        self.assertEqual(stale.status, 'expired')
        self.assertLess(stale.expires_at, timezone.now())

    def test_opening_the_list_expires_due_invites(self) -> None:
        stale = self.invite('stale@example.com', expires_at=timezone.now() - timedelta(days=1))
        self.client.get(self.CHANGELIST)
        stale.refresh_from_db()
        self.assertEqual(stale.status, 'expired')

    def test_admin_cannot_add_invites_or_edit_fields(self) -> None:
        invite = self.invite('a@example.com')
        self.assertEqual(self.client.get(self.CHANGELIST + 'add/').status_code, 403)
        self.client.post(f'{self.CHANGELIST}{invite.pk}/change/', {'status': 'registered', 'full_name': 'Hacked'})
        invite.refresh_from_db()
        self.assertEqual((invite.status, invite.full_name), ('invited', 'X Y'))

    def test_members_and_anonymous_cannot_reach_admin(self) -> None:
        member = self.make_member()
        member_client = Client()
        member_client.force_login(member)
        for client in (Client(), member_client):
            response = client.get(self.CHANGELIST)
            self.assertEqual(response.status_code, 302)
            self.assertIn('/admin/login/', response['Location'])

    def test_staff_without_permission_is_denied(self) -> None:
        plain_staff = User.objects.create_user(
            full_name='Plain Staff', password=PASSWORD, email='staff@example.com', is_staff=True, email_verified=True,
        )
        client = Client()
        client.force_login(plain_staff)
        invite = self.invite('a@example.com')
        self.assertEqual(client.get(self.CHANGELIST).status_code, 403)
        client.post(self.CHANGELIST, {'action': 'cancel_invites', '_selected_action': [invite.pk]})
        invite.refresh_from_db()
        self.assertEqual(invite.status, 'invited')


class ReviewAdminBase(MembershipBaseTestCase):
    """Review work is done in the Unfold admin site (staff + permission), not through REST."""

    def setUp(self) -> None:
        super().setUp()
        self.staff = User.objects.create_superuser(full_name='Super Admin', password=PASSWORD, email='super@example.com')
        self.client = Client()
        self.client.force_login(self.staff)

    def decide(self, url: str, decision: str = '', remarks: str = '', client: Client | None = None):
        return (client or self.client).post(url, {'decision': decision, 'admin_remarks': remarks, '_save': 'Save'}, follow=True)

    def messages(self, response) -> str:
        return ' '.join(str(m) for m in response.context['messages']) if response.context else ''


class ReferralAdminReviewTests(ReviewAdminBase):
    def flagged(self, referrer: User | None = None, verified_contact: bool = True) -> Referral:
        referrer = referrer or self.make_member()
        return Referral.objects.create(
            referrer=referrer, referred=self.make_member(verified=verified_contact),
            status=ReferralStatus.FLAGGED, flag_reason='same IP',
        )

    @staticmethod
    def url(referral: Referral) -> str:
        return f'/admin/membership/referral/{referral.pk}/change/'

    def test_pages_render_and_show_fraud_details(self) -> None:
        referral = self.flagged()
        referral.referred.registration_ip = '10.1.2.3'
        referral.referred.save()
        self.assertEqual(self.client.get('/admin/membership/referral/?status__exact=flagged').status_code, 200)
        page = self.client.get(self.url(referral))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'same IP')
        self.assertContains(page, '10.1.2.3')

    def test_approve_verified_referred_counts_and_promotes_at_five(self) -> None:
        referrer = self.make_member()
        for _ in range(4):
            self.verified_referral(referrer)
        referral = self.flagged(referrer)
        self.decide(self.url(referral), 'approve', 'Looks fine')
        referral.refresh_from_db()
        self.assertEqual((referral.status, referral.reviewed_by_id), ('verified', self.staff.user_id))
        self.assertEqual(self.level(referrer), 'active')

    def test_approve_unverified_referred_goes_back_to_pending(self) -> None:
        referral = self.flagged(verified_contact=False)
        self.decide(self.url(referral), 'approve')
        referral.refresh_from_db()
        self.assertEqual(referral.status, 'pending')
        self.assertEqual(Referral.verified_count(referral.referrer_id), 0)

    def test_reject_needs_remarks_then_never_counts(self) -> None:
        referral = self.flagged()
        blocked = self.decide(self.url(referral), 'reject')
        referral.refresh_from_db()
        self.assertEqual(referral.status, 'flagged')
        self.assertContains(blocked, 'Remarks are required')
        self.decide(self.url(referral), 'reject', 'Same household')
        referral.refresh_from_db()
        self.assertEqual((referral.status, referral.admin_remarks), ('rejected', 'Same household'))
        self.assertEqual(Referral.verified_count(referral.referrer_id), 0)

    def test_decided_or_unflagged_referral_is_locked(self) -> None:
        verified = self.verified_referral(self.make_member())
        response = self.decide(self.url(verified), 'reject', 'x')
        verified.refresh_from_db()
        self.assertEqual(verified.status, 'verified')
        self.assertContains(response, 'already been decided')

    def test_cannot_add_or_delete(self) -> None:
        referral = self.flagged()
        self.assertEqual(self.client.get('/admin/membership/referral/add/').status_code, 403)
        self.assertEqual(self.client.get(self.url(referral).replace('change/', 'delete/')).status_code, 403)

    def test_only_permitted_staff_can_review(self) -> None:
        referral = self.flagged()
        plain_staff = User.objects.create_user(
            full_name='Plain Staff', password=PASSWORD, email='staff@example.com', is_staff=True, email_verified=True,
        )
        staff_client, member_client = Client(), Client()
        staff_client.force_login(plain_staff)
        member_client.force_login(self.make_member())
        self.assertEqual(staff_client.get(self.url(referral)).status_code, 403)
        self.decide(self.url(referral), 'approve', client=staff_client)
        self.assertEqual(Client().get(self.url(referral)).status_code, 302)
        self.assertEqual(member_client.get(self.url(referral)).status_code, 302)
        referral.refresh_from_db()
        self.assertEqual(referral.status, 'flagged')

    def test_members_never_see_flags(self) -> None:
        referrer = self.make_member()
        self.flagged(referrer)
        response = self.as_user(referrer).get('/membership/referral/get_all/')
        self.assertEqual(response.data['data']['data'][0]['status'], 'under_review')
        for leaked in ('flagged', 'same IP', 'flagReason', 'registrationIp', 'referredMembershipId'):
            self.assertNotIn(leaked, str(response.data))

    def test_model_review_rules(self) -> None:
        referral = self.flagged()
        with self.assertRaises(ValueError):
            Referral.review(referral.pk, self.staff, 'maybe')
        with self.assertRaises(NotFoundError):
            Referral.review(999999, self.staff, 'approve')


class PermanentApplicationAdminReviewTests(ReviewAdminBase):
    @staticmethod
    def url(application: PermanentApplication) -> str:
        return f'/admin/membership/permanentapplication/{application.pk}/change/'

    def application(self, **member_extra) -> PermanentApplication:
        return PermanentApplication.objects.create(user=self.make_member(level='active', **member_extra), reason=REASON)

    def test_approve_makes_member_permanent(self) -> None:
        application = self.application()
        self.decide(self.url(application), 'approve', 'Welcome')
        application.refresh_from_db()
        self.assertEqual((application.status, application.reviewed_by_id), ('approved', self.staff.user_id))
        self.assertEqual(self.level(application.user), 'permanent')
        profile = self.as_user(application.user).get('/auth/profile/get/').data['data']
        self.assertEqual(profile['membershipLevel'], 'permanent')

    def test_reject_needs_remarks_keeps_level_and_allows_reapply(self) -> None:
        application = self.application()
        blocked = self.decide(self.url(application), 'reject')
        self.assertContains(blocked, 'Remarks are required')
        application.refresh_from_db()
        self.assertEqual(application.status, 'pending')
        self.decide(self.url(application), 'reject', 'Need more history')
        application.refresh_from_db()
        self.assertEqual(application.status, 'rejected')
        self.assertEqual(self.level(application.user), 'active')
        seen = self.as_user(application.user).get(
            f'/membership/permanent_application/get/?application_id={application.application_id}',
        )
        self.assertEqual(seen.data['data']['adminRemarks'], 'Need more history')
        again = self.as_user(application.user).post(
            '/membership/permanent_application/create/', {'reason': REASON}, format='json',
        )
        self.assertEqual(again.status_code, 200)

    def test_cannot_review_twice_or_edit_decided_remarks(self) -> None:
        application = self.application()
        self.decide(self.url(application), 'approve', 'ok')
        response = self.decide(self.url(application), 'reject', 'changed my mind')
        application.refresh_from_db()
        self.assertEqual((application.status, application.admin_remarks), ('approved', 'ok'))
        self.assertContains(response, 'already been decided')
        self.decide(self.url(application), '', 'rewritten')
        application.refresh_from_db()
        self.assertEqual(application.admin_remarks, 'ok')
        self.assertEqual(self.level(application.user), 'permanent')

    def test_inactive_member_cannot_be_approved(self) -> None:
        application = self.application(is_active=False)
        response = self.decide(self.url(application), 'approve')
        application.refresh_from_db()
        self.assertEqual(application.status, 'pending')
        self.assertContains(response, 'not active')
        self.assertEqual(self.level(application.user), 'active')

    def test_remarks_only_save_keeps_it_pending(self) -> None:
        application = self.application()
        self.decide(self.url(application), '', 'Asked member for documents')
        application.refresh_from_db()
        self.assertEqual((application.status, application.admin_remarks), ('pending', 'Asked member for documents'))
        self.assertEqual(self.level(application.user), 'active')

    def test_list_filter_search_and_verified_referral_column(self) -> None:
        first, second = self.application(), self.application()
        for _ in range(2):
            self.verified_referral(first.user)
        second.status = 'approved'
        second.save()
        listing = self.client.get('/admin/membership/permanentapplication/')
        self.assertEqual(listing.status_code, 200)
        counts = {row.pk: row.verified_count for row in listing.context['cl'].result_list}
        self.assertEqual((counts[first.pk], counts[second.pk]), (2, 0))
        pending = self.client.get('/admin/membership/permanentapplication/?status__exact=pending')
        self.assertEqual([r.pk for r in pending.context['cl'].result_list], [first.pk])
        found = self.client.get(f'/admin/membership/permanentapplication/?q={second.user.membership_id}')
        self.assertEqual([r.pk for r in found.context['cl'].result_list], [second.pk])

    def test_members_and_anonymous_blocked_and_no_add_delete(self) -> None:
        application = self.application()
        member_client = Client()
        member_client.force_login(application.user)
        self.assertEqual(member_client.get(self.url(application)).status_code, 302)
        self.decide(self.url(application), 'approve', client=member_client)
        self.assertEqual(Client().get(self.url(application)).status_code, 302)
        self.assertEqual(self.client.get('/admin/membership/permanentapplication/add/').status_code, 403)
        self.assertEqual(self.client.get(self.url(application).replace('change/', 'delete/')).status_code, 403)
        application.refresh_from_db()
        self.assertEqual((application.status, self.level(application.user)), ('pending', 'active'))

    def test_model_review_rules(self) -> None:
        application = self.application()
        with self.assertRaises(ValueError):
            PermanentApplication.review(application.pk, self.staff, 'maybe')
        with self.assertRaises(ValueError):
            PermanentApplication.review(application.pk, self.staff, 'reject', '  ')
        with self.assertRaises(NotFoundError):
            PermanentApplication.review(999999, self.staff, 'approve')


class ExpiryTimerTests(MembershipBaseTestCase):
    def test_task_expires_only_due_open_invites_and_is_idempotent(self) -> None:
        member = self.make_member()
        past = timezone.now() - timedelta(minutes=1)
        due = ReferralInvite.objects.create(referrer=member, full_name='A', email='a@example.com', expires_at=past)
        later = ReferralInvite.objects.create(referrer=member, full_name='B', email='b@example.com')
        done = ReferralInvite.objects.create(referrer=member, full_name='C', email='c@example.com', status='registered', expires_at=past)
        self.assertEqual(expire_referral_invites.apply().get(), 1)
        self.assertEqual(expire_referral_invites.apply().get(), 0)
        statuses = {i.email: i.status for i in ReferralInvite.objects.all()}
        self.assertEqual(statuses, {due.email: 'expired', later.email: 'invited', done.email: 'registered'})

    def test_task_is_registered_and_scheduled_by_beat(self) -> None:
        from gmp.celery import app

        app.loader.import_default_modules()
        name = 'gmp_apps.membership.tasks.expire_referral_invites'
        self.assertIn(name, app.tasks)
        entry = settings.CELERY_BEAT_SCHEDULE['expire-referral-invites']
        self.assertEqual(entry['task'], name)
        self.assertEqual(entry['schedule'], Configurations.invite_expiry_interval_minutes * 60)
        self.assertGreaterEqual(entry['schedule'], 60)

    def test_missed_timer_never_lets_expired_invite_link(self) -> None:
        """Lazy expiry stays as a safety net even if the timer has not run."""
        member = self.make_member()
        ReferralInvite.objects.create(
            referrer=member, full_name='A', email='late@example.com', expires_at=timezone.now() - timedelta(minutes=1),
        )
        response = APIClient().post(
            '/auth/register/', {'full_name': 'Late One', 'email': 'late@example.com', 'password': PASSWORD}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Referral.objects.exists())


class SwaggerTests(MembershipBaseTestCase):
    def test_all_membership_paths_in_schema(self) -> None:
        body = APIClient().get('/api/schema/').content.decode()
        self.assertNotIn('/membership/admin/', body)  # admin work lives in the Unfold admin site
        for path in (
            'progress/get', 'referral/get_all', 'referral_invite/create', 'referral_invite/get_all', 'referral_invite/delete', 'permanent_application/create', 'permanent_application/get',
            'permanent_application/get_all',
        ):
            self.assertIn(f'/membership/{path}/', body)
