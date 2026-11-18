from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import Group, Permission
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from gmp.config import Configurations
from gmp_apps.authentication.models import Otp, User
from gmp_apps.authentication.otp_delivery import LocMemOtpBackend
from gmp_apps.common.exceptions.errors import ForbiddenError
from gmp_apps.membership.models import PermanentApplication, Referral, ReferralInvite

STRONG_PASSWORD = 'Sunrise#Valley42'
NEW_PASSWORD = 'Another#Pass917'
LOCMEM = 'gmp_apps.authentication.otp_delivery.LocMemOtpBackend'
FAST_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']


@override_settings(OTP_DELIVERY_BACKEND=LOCMEM, PASSWORD_HASHERS=FAST_HASHERS)
class AuthBaseTestCase(APITestCase):
    def setUp(self) -> None:
        cache.clear()
        LocMemOtpBackend.outbox.clear()

    def post(self, name: str, data: dict, token: str | None = None):
        headers = {'HTTP_AUTHORIZATION': f'Bearer {token}'} if token else {}
        return self.client.post(f'/auth/{name}/', data, format='json', **headers)

    def last_otp(self, destination: str) -> str:
        return [m for m in LocMemOtpBackend.outbox if m['destination'] == destination][-1]['code']

    def register(self, **overrides) -> dict:
        payload = {'full_name': 'Asha Verma', 'email': 'asha@example.com', 'password': STRONG_PASSWORD}
        payload.update(overrides)
        response = self.post('register', payload)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def verified_user(self, email: str = 'asha@example.com', **extra) -> User:
        self.register(email=email, **extra)
        self.post('verify_otp', {'identifier': email, 'otp': self.last_otp(email)})
        return User.objects.get(email=email)

    def login(self, identifier: str = 'asha@example.com', password: str = STRONG_PASSWORD) -> dict:
        response = self.post('login', {'identifier': identifier, 'password': password})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']


class RegistrationTests(AuthBaseTestCase):
    def test_register_with_email_creates_general_member_with_codes(self) -> None:
        body = self.register()
        user = User.objects.get(email='asha@example.com')
        self.assertTrue(body['status'])
        self.assertEqual(user.membership_level, 'general')
        self.assertEqual(user.role, 'member')
        self.assertTrue(user.membership_id.startswith('GM'))
        self.assertTrue(user.referral_code.startswith('R'))
        self.assertEqual(body['data']['membershipId'], user.membership_id)
        self.assertFalse(user.email_verified)

    def test_register_with_mobile_only(self) -> None:
        response = self.post('register', {'full_name': 'Ravi', 'mobile_number': '+91 98765 43210', 'password': STRONG_PASSWORD})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(User.objects.get().mobile_number, '+919876543210')

    def test_register_with_both_sends_two_otps(self) -> None:
        self.register(mobile_number='9876543210')
        channels = sorted(m['channel'] for m in LocMemOtpBackend.outbox)
        self.assertEqual(channels, ['email', 'mobile'])

    def test_codes_are_unique_across_users(self) -> None:
        self.register(email='a@example.com')
        self.register(email='b@example.com')
        ids = User.objects.values_list('membership_id', 'referral_code')
        self.assertEqual(len({i[0] for i in ids}), 2)
        self.assertEqual(len({i[1] for i in ids}), 2)

    def test_otp_and_password_never_in_response(self) -> None:
        body = self.register()
        text = str(body)
        self.assertNotIn(self.last_otp('asha@example.com'), text)
        self.assertNotIn(STRONG_PASSWORD, text)

    def test_otp_is_stored_hashed(self) -> None:
        self.register()
        self.assertNotEqual(Otp.objects.get().code_hash, self.last_otp('asha@example.com'))

    def test_requires_email_or_mobile(self) -> None:
        response = self.post('register', {'full_name': 'X', 'password': STRONG_PASSWORD})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data['status'])

    def test_duplicate_email_and_mobile_rejected(self) -> None:
        self.register(mobile_number='9876543210')
        dup_email = self.post('register', {'full_name': 'B', 'email': 'ASHA@example.com', 'password': STRONG_PASSWORD})
        dup_mobile = self.post('register', {'full_name': 'B', 'mobile_number': '98765 43210', 'password': STRONG_PASSWORD})
        self.assertEqual(dup_email.status_code, 400)
        self.assertEqual(dup_mobile.status_code, 400)
        self.assertEqual(User.objects.count(), 1)

    def test_invalid_mobile_and_weak_password_rejected(self) -> None:
        bad_mobile = self.post('register', {'full_name': 'B', 'mobile_number': '12', 'password': STRONG_PASSWORD})
        weak = self.post('register', {'full_name': 'B', 'email': 'b@example.com', 'password': 'password'})
        self.assertEqual(bad_mobile.status_code, 400)
        self.assertEqual(weak.status_code, 400)

    def test_register_ignores_privileged_fields(self) -> None:
        self.register(role='admin', membership_level='permanent', is_staff=True)
        user = User.objects.get()
        self.assertEqual((user.role, user.membership_level, user.is_staff), ('member', 'general', False))


class OtpVerificationTests(AuthBaseTestCase):
    def test_verify_marks_channel_verified(self) -> None:
        user = self.verified_user()
        self.assertTrue(user.email_verified)
        self.assertFalse(user.mobile_verified)

    def test_wrong_otp_rejected_and_attempts_capped(self) -> None:
        self.register()
        good = self.last_otp('asha@example.com')
        with mock.patch.object(Configurations, 'otp_max_attempts', 2):
            for _ in range(2):
                self.assertEqual(self.post('verify_otp', {'identifier': 'asha@example.com', 'otp': '000000'}).status_code, 400)
            locked = self.post('verify_otp', {'identifier': 'asha@example.com', 'otp': good})
        self.assertEqual(locked.status_code, 400)
        self.assertFalse(User.objects.get().email_verified)

    def test_expired_and_reused_otp_rejected(self) -> None:
        self.register()
        code = self.last_otp('asha@example.com')
        Otp.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.post('verify_otp', {'identifier': 'asha@example.com', 'otp': code}).status_code, 400)
        self.verified_user(email='fresh@example.com')
        again = self.post('verify_otp', {'identifier': 'fresh@example.com', 'otp': self.last_otp('fresh@example.com')})
        self.assertEqual(again.status_code, 400)

    def test_unknown_identifier_gets_same_error_as_wrong_otp(self) -> None:
        self.register()
        unknown = self.post('verify_otp', {'identifier': 'nobody@example.com', 'otp': '123456'})
        wrong = self.post('verify_otp', {'identifier': 'asha@example.com', 'otp': '123456'})
        self.assertEqual(unknown.data['error'], wrong.data['error'])

    def test_resend_respects_cooldown_and_hides_existence(self) -> None:
        self.register()
        sent = len(LocMemOtpBackend.outbox)
        inside = self.post('resend_otp', {'identifier': 'asha@example.com'})
        unknown = self.post('resend_otp', {'identifier': 'nobody@example.com'})
        self.assertEqual(len(LocMemOtpBackend.outbox), sent)
        self.assertEqual(inside.data, unknown.data)
        with mock.patch.object(Configurations, 'otp_resend_cooldown_seconds', 0):
            self.post('resend_otp', {'identifier': 'asha@example.com'})
        self.assertEqual(len(LocMemOtpBackend.outbox), sent + 1)

    def test_resend_invalidates_previous_otp(self) -> None:
        self.register()
        old = self.last_otp('asha@example.com')
        with mock.patch.object(Configurations, 'otp_resend_cooldown_seconds', 0):
            self.post('resend_otp', {'identifier': 'asha@example.com'})
        new = self.last_otp('asha@example.com')
        if old != new:
            self.assertEqual(self.post('verify_otp', {'identifier': 'asha@example.com', 'otp': old}).status_code, 400)
        self.assertEqual(self.post('verify_otp', {'identifier': 'asha@example.com', 'otp': new}).status_code, 200)


class LoginTests(AuthBaseTestCase):
    def test_login_success_returns_tokens_and_profile(self) -> None:
        self.verified_user()
        data = self.login()
        self.assertIn('access', data)
        self.assertIn('refresh', data)
        self.assertEqual(data['user']['membershipLevel'], 'general')
        self.assertNotIn('password', data['user'])

    def test_login_with_verified_mobile(self) -> None:
        self.register(email=None, mobile_number='9876543210')
        self.post('verify_otp', {'identifier': '9876543210', 'otp': self.last_otp('9876543210')})
        self.assertIn('access', self.login(identifier='9876543210'))

    def test_unverified_account_forbidden(self) -> None:
        self.register()
        response = self.post('login', {'identifier': 'asha@example.com', 'password': STRONG_PASSWORD})
        self.assertEqual(response.status_code, 403)

    def test_unverified_other_channel_cannot_be_used(self) -> None:
        self.register(mobile_number='9876543210')
        self.post('verify_otp', {'identifier': 'asha@example.com', 'otp': self.last_otp('asha@example.com')})
        response = self.post('login', {'identifier': '9876543210', 'password': STRONG_PASSWORD})
        self.assertEqual(response.status_code, 403)

    def test_wrong_password_and_unknown_user_look_identical(self) -> None:
        self.verified_user()
        wrong = self.post('login', {'identifier': 'asha@example.com', 'password': 'Wrong#Pass123'})
        unknown = self.post('login', {'identifier': 'nobody@example.com', 'password': 'Wrong#Pass123'})
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(unknown.status_code, 401)
        self.assertEqual(wrong.data, unknown.data)

    def test_suspended_account_forbidden(self) -> None:
        user = self.verified_user()
        user.is_active = False
        user.save()
        response = self.post('login', {'identifier': 'asha@example.com', 'password': STRONG_PASSWORD})
        self.assertEqual(response.status_code, 403)

    def test_login_is_throttled(self) -> None:
        statuses = [
            self.post('login', {'identifier': 'x@example.com', 'password': 'Wrong#Pass123'}).status_code
            for _ in range(35)
        ]
        self.assertIn(429, statuses)


class TokenTests(AuthBaseTestCase):
    def test_refresh_rotates_and_revokes_old_token(self) -> None:
        self.verified_user()
        old = self.login()['refresh']
        rotated = self.post('refresh', {'refresh': old})
        self.assertEqual(rotated.status_code, 200)
        self.assertNotEqual(rotated.data['data']['refresh'], old)
        self.assertEqual(self.post('refresh', {'refresh': old}).status_code, 401)

    def test_refresh_rejects_garbage_and_suspended_user(self) -> None:
        user = self.verified_user()
        refresh = self.login()['refresh']
        self.assertEqual(self.post('refresh', {'refresh': 'garbage'}).status_code, 401)
        user.is_active = False
        user.save()
        self.assertEqual(self.post('refresh', {'refresh': refresh}).status_code, 401)

    def test_logout_revokes_refresh_token(self) -> None:
        self.verified_user()
        tokens = self.login()
        self.assertEqual(self.post('logout', {'refresh': tokens['refresh']}, token=tokens['access']).status_code, 200)
        self.assertEqual(self.post('refresh', {'refresh': tokens['refresh']}).status_code, 401)

    def test_logout_requires_auth_and_ownership(self) -> None:
        self.verified_user()
        mine = self.login()
        self.verified_user(email='other@example.com')
        theirs = self.login(identifier='other@example.com')
        self.assertEqual(self.post('logout', {'refresh': mine['refresh']}).status_code, 401)
        stolen = self.post('logout', {'refresh': theirs['refresh']}, token=mine['access'])
        self.assertEqual(stolen.status_code, 403)
        self.assertEqual(self.post('refresh', {'refresh': theirs['refresh']}).status_code, 200)

    def test_refresh_token_cannot_be_used_as_access_token(self) -> None:
        self.verified_user()
        refresh = self.login()['refresh']
        response = self.client.get('/auth/profile/get/', HTTP_AUTHORIZATION=f'Bearer {refresh}')
        self.assertEqual(response.status_code, 401)


class PasswordTests(AuthBaseTestCase):
    def test_change_password_success_revokes_old_sessions(self) -> None:
        self.verified_user()
        tokens = self.login()
        response = self.post('change_password', {'old_password': STRONG_PASSWORD, 'new_password': NEW_PASSWORD}, token=tokens['access'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.post('refresh', {'refresh': tokens['refresh']}).status_code, 401)
        self.assertIn('access', self.login(password=NEW_PASSWORD))

    def test_change_password_rejects_wrong_old_and_weak_new(self) -> None:
        self.verified_user()
        token = self.login()['access']
        wrong = self.post('change_password', {'old_password': 'nope', 'new_password': NEW_PASSWORD}, token=token)
        weak = self.post('change_password', {'old_password': STRONG_PASSWORD, 'new_password': '12345678'}, token=token)
        similar = self.post('change_password', {'old_password': STRONG_PASSWORD, 'new_password': 'asha@example.com'}, token=token)
        self.assertEqual((wrong.status_code, weak.status_code, similar.status_code), (400, 400, 400))

    def test_change_password_requires_auth(self) -> None:
        response = self.post('change_password', {'old_password': 'a', 'new_password': 'b'})
        self.assertEqual(response.status_code, 401)

    def test_forgot_then_reset_password(self) -> None:
        self.verified_user()
        tokens = self.login()
        LocMemOtpBackend.outbox.clear()
        self.assertEqual(self.post('forgot_password', {'identifier': 'asha@example.com'}).status_code, 200)
        code = self.last_otp('asha@example.com')
        reset = self.post('reset_password', {'identifier': 'asha@example.com', 'otp': code, 'new_password': NEW_PASSWORD})
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(self.post('refresh', {'refresh': tokens['refresh']}).status_code, 401)
        self.assertEqual(self.post('login', {'identifier': 'asha@example.com', 'password': STRONG_PASSWORD}).status_code, 401)
        self.assertIn('access', self.login(password=NEW_PASSWORD))

    def test_forgot_password_does_not_reveal_accounts(self) -> None:
        self.verified_user()
        known = self.post('forgot_password', {'identifier': 'asha@example.com'})
        unknown = self.post('forgot_password', {'identifier': 'nobody@example.com'})
        self.assertEqual(known.data, unknown.data)

    def test_forgot_password_not_sent_to_unverified_contact(self) -> None:
        self.register()
        LocMemOtpBackend.outbox.clear()
        self.post('forgot_password', {'identifier': 'asha@example.com'})
        self.assertEqual(LocMemOtpBackend.outbox, [])

    def test_account_recovery_via_other_verified_contact(self) -> None:
        self.register(mobile_number='9876543210')
        for who in ('asha@example.com', '9876543210'):
            self.post('verify_otp', {'identifier': who, 'otp': self.last_otp(who)})
        LocMemOtpBackend.outbox.clear()
        self.post('forgot_password', {'identifier': '9876543210'})
        reset = self.post('reset_password', {
            'identifier': '9876543210', 'otp': self.last_otp('9876543210'), 'new_password': NEW_PASSWORD,
        })
        self.assertEqual(reset.status_code, 200)
        self.assertIn('access', self.login(identifier='asha@example.com', password=NEW_PASSWORD))

    def test_reset_with_wrong_otp_or_weak_password_rejected(self) -> None:
        self.verified_user()
        self.post('forgot_password', {'identifier': 'asha@example.com'})
        code = self.last_otp('asha@example.com')
        bad_otp = self.post('reset_password', {'identifier': 'asha@example.com', 'otp': '000000', 'new_password': NEW_PASSWORD})
        weak = self.post('reset_password', {'identifier': 'asha@example.com', 'otp': code, 'new_password': 'short'})
        self.assertEqual((bad_otp.status_code, weak.status_code), (400, 400))

    def test_registration_otp_cannot_reset_password(self) -> None:
        self.register()
        code = self.last_otp('asha@example.com')
        response = self.post('reset_password', {'identifier': 'asha@example.com', 'otp': code, 'new_password': NEW_PASSWORD})
        self.assertEqual(response.status_code, 400)


class ProfileTests(AuthBaseTestCase):
    def test_anonymous_gets_401_envelope(self) -> None:
        for response in (self.client.get('/auth/profile/get/'), self.client.put('/auth/profile/update/', {}, format='json')):
            self.assertEqual(response.status_code, 401)
            self.assertFalse(response.data['status'])

    def test_get_own_profile(self) -> None:
        user = self.verified_user()
        token = self.login()['access']
        response = self.client.get('/auth/profile/get/', HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(response.status_code, 200)
        data = response.data['data']
        self.assertEqual(data['membershipId'], user.membership_id)
        self.assertEqual(data['referralCode'], user.referral_code)
        self.assertEqual(data['membershipLevel'], 'general')

    def test_update_editable_fields(self) -> None:
        self.verified_user()
        token = self.login()['access']
        response = self.client.put(
            '/auth/profile/update/',
            {'full_name': 'Asha V', 'date_of_birth': '1990-05-17', 'gender': 'female', 'state': 'Gujarat', 'city': 'Surat'},
            format='json', HTTP_AUTHORIZATION=f'Bearer {token}',
        )
        self.assertEqual(response.status_code, 200, response.data)
        user = User.objects.get()
        self.assertEqual((user.full_name, user.city, user.gender), ('Asha V', 'Surat', 'female'))

    def test_member_cannot_edit_status_identity_or_codes(self) -> None:
        user = self.verified_user()
        token = self.login()['access']
        response = self.client.put(
            '/auth/profile/update/',
            {'city': 'Surat', 'membership_level': 'permanent', 'role': 'admin', 'is_staff': True,
             'email': 'new@example.com', 'referral_code': 'HACK', 'membership_id': 'GMHACK'},
            format='json', HTTP_AUTHORIZATION=f'Bearer {token}',
        )
        self.assertEqual(response.status_code, 200)
        fresh = User.objects.get()
        self.assertEqual(
            (fresh.membership_level, fresh.role, fresh.is_staff, fresh.email, fresh.referral_code, fresh.membership_id),
            ('general', 'member', False, 'asha@example.com', user.referral_code, user.membership_id),
        )

    def test_update_validation_errors(self) -> None:
        self.verified_user()
        token = self.login()['access']
        auth = {'HTTP_AUTHORIZATION': f'Bearer {token}'}
        self.assertEqual(self.client.put('/auth/profile/update/', {}, format='json', **auth).status_code, 400)
        self.assertEqual(self.client.put('/auth/profile/update/', {'gender': 'x'}, format='json', **auth).status_code, 400)

    def test_idor_user_id_parameter_is_ignored(self) -> None:
        self.verified_user(email='victim@example.com')
        victim = User.objects.get(email='victim@example.com')
        self.verified_user(email='asha@example.com')
        token = self.login()['access']
        auth = {'HTTP_AUTHORIZATION': f'Bearer {token}'}
        got = self.client.get(f'/auth/profile/get/?user_id={victim.user_id}&userId={victim.user_id}', **auth)
        self.assertEqual(got.data['data']['email'], 'asha@example.com')
        self.client.put('/auth/profile/update/', {'user_id': victim.user_id, 'city': 'Pwned'}, format='json', **auth)
        victim.refresh_from_db()
        self.assertEqual(victim.city, '')

    def test_suspended_user_token_stops_working(self) -> None:
        user = self.verified_user()
        token = self.login()['access']
        user.is_active = False
        user.save()
        response = self.client.get('/auth/profile/get/', HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(response.status_code, 401)


class SwaggerTests(AuthBaseTestCase):
    def test_schema_generates_and_documents_every_endpoint(self) -> None:
        response = self.client.get('/api/schema/')
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        for path in ('register', 'verify_otp', 'resend_otp', 'login', 'refresh', 'logout',
                     'change_password', 'forgot_password', 'reset_password', 'profile/get', 'profile/update'):
            self.assertIn(f'/auth/{path}/', body)


class AdminManagementTestCase(AuthBaseTestCase):
    """Member management in the Unfold admin site: view, suspend, access management, dashboard."""

    LIST = '/admin/authentication/user/'

    def setUp(self) -> None:
        super().setUp()
        call_command('setup_admin_groups', stdout=StringIO())
        self.superuser = User.objects.create_superuser(full_name='Super Admin', password=STRONG_PASSWORD, email='super@example.com')
        self.counter = 0

    def staff(self, *groups: str, email: str | None = None) -> User:
        self.counter += 1
        user = User.objects.create_user(
            full_name='Staff Person', password=STRONG_PASSWORD, email=email or f'staff{self.counter}@example.com',
            is_staff=True, role='admin', email_verified=True,
        )
        user.groups.add(*Group.objects.filter(name__in=groups))
        return user

    def member(self, **extra) -> User:
        self.counter += 1
        return User.objects.create_user(
            full_name=f'Member {self.counter}', password=STRONG_PASSWORD, email=f'm{self.counter}@example.com',
            email_verified=True, **extra,
        )

    @staticmethod
    def client_for(user: User | None) -> Client:
        client = Client()
        if user:
            client.force_login(user)
        return client

    def url(self, user: User) -> str:
        return f'{self.LIST}{user.pk}/change/'

    def post_user(self, actor: User, target: User, **overrides):
        data = {
            'is_active': 'on' if target.is_active else '', 'suspended_reason': target.suspended_reason, 'role': target.role,
            'is_staff': 'on' if target.is_staff else '', 'is_superuser': 'on' if target.is_superuser else '',
            'groups': [g.pk for g in target.groups.all()], 'user_permissions': [], '_save': 'Save',
        }
        data.update(overrides)
        data = {k: v for k, v in data.items() if v != ''}
        return self.client_for(actor).post(self.url(target), data, follow=True)


class AdminSetupTests(AdminManagementTestCase):
    def test_createsuperuser_works_with_generated_membership_id(self) -> None:
        env = {'DJANGO_SUPERUSER_PASSWORD': STRONG_PASSWORD}
        with mock.patch.dict('os.environ', env):
            call_command('createsuperuser', interactive=False, membership_id='IGNORED', full_name='Root Admin',
                         email='root@example.com', stdout=StringIO())
        root = User.objects.get(email='root@example.com')
        self.assertTrue(root.is_superuser and root.is_staff)
        self.assertEqual(root.role, 'admin')
        self.assertTrue(root.membership_id.startswith('GM'))
        self.assertNotEqual(root.membership_id, 'IGNORED')

    def test_groups_command_is_exact_and_idempotent(self) -> None:
        call_command('setup_admin_groups', stdout=StringIO())
        managers = set(Group.objects.get(name='Member Managers').permissions.values_list('codename', flat=True))
        reviewers = set(Group.objects.get(name='Membership Reviewers').permissions.values_list('codename', flat=True))
        self.assertEqual(managers, {'view_user', 'change_user', 'suspend_member'})
        self.assertEqual(reviewers, {
            'view_referral', 'change_referral', 'view_permanentapplication', 'change_permanentapplication',
            'view_referralinvite', 'change_referralinvite',
        })
        support = set(Group.objects.get(name='Support Handlers').permissions.values_list('codename', flat=True))
        self.assertEqual(support, {
            'view_contactrequest', 'change_contactrequest', 'view_contactcategory', 'add_contactcategory',
            'change_contactcategory',
        })
        self.assertEqual(Group.objects.count(), 10)

    def test_admin_login_by_email_or_membership_id_staff_only(self) -> None:
        staff = self.staff('Member Managers')
        member = self.member()
        for username in (staff.email, staff.membership_id, staff.membership_id.lower()):
            client = Client()
            response = client.post('/admin/login/?next=/admin/', {'username': username, 'password': STRONG_PASSWORD})
            self.assertEqual(response.status_code, 302, username)
            self.assertEqual(client.get('/admin/').status_code, 200)
        for username, password in ((member.email, STRONG_PASSWORD), (staff.email, 'Wrong#Pass123'), ('nobody@example.com', STRONG_PASSWORD)):
            client = Client()
            client.post('/admin/login/?next=/admin/', {'username': username, 'password': password})
            self.assertEqual(client.get('/admin/').status_code, 302, username)


class AdminBackendTests(AdminManagementTestCase):
    def test_backend_refuses_non_staff_and_inactive_and_wrong_password(self) -> None:
        from django.contrib.auth import authenticate

        staff, member = self.staff('Member Managers'), self.member()
        self.assertEqual(authenticate(username=staff.email, password=STRONG_PASSWORD), staff)
        self.assertEqual(authenticate(username=staff.membership_id, password=STRONG_PASSWORD), staff)
        self.assertIsNone(authenticate(username=member.email, password=STRONG_PASSWORD))
        self.assertIsNone(authenticate(username=staff.email, password='Wrong#Pass123'))
        User.objects.filter(pk=staff.pk).update(is_active=False)
        self.assertIsNone(authenticate(username=staff.email, password=STRONG_PASSWORD))


class AdminMemberViewTests(AdminManagementTestCase):
    def test_search_filter_and_detail(self) -> None:
        manager = self.staff('Member Managers')
        target = self.member(mobile_number='9876543210')
        other = self.member(membership_level='active')
        client = self.client_for(manager)
        for query in (target.email, target.mobile_number, target.membership_id, target.referral_code):
            rows = client.get(f'{self.LIST}?q={query}').context['cl'].result_list
            self.assertEqual([r.pk for r in rows], [target.pk], query)
        active = client.get(f'{self.LIST}?membership_level__exact=active').context['cl'].result_list
        self.assertEqual([r.pk for r in active], [other.pk])
        page = client.get(self.url(target))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, target.referral_code)

    def test_detail_shows_qualifying_referrals_and_referrer(self) -> None:
        manager = self.staff('Member Managers')
        referrer, referred = self.member(), self.member()
        Referral.objects.create(referrer=referrer, referred=referred, status='verified')
        listing = self.client_for(manager).get(self.LIST)
        counts = {u.pk: u.verified_count for u in listing.context['cl'].result_list}
        self.assertEqual((counts[referrer.pk], counts[referred.pk]), (1, 0))
        self.assertContains(self.client_for(manager).get(self.url(referred)), referrer.membership_id)

    def test_profile_and_level_are_read_only_even_for_superuser(self) -> None:
        target = self.member()
        self.post_user(self.superuser, target, membership_level='permanent', full_name='Hacked', email='x@example.com',
                       referral_code='HACKED', email_verified='on')
        target.refresh_from_db()
        self.assertEqual((target.membership_level, target.full_name, target.referral_code), ('general', target.full_name, target.referral_code))
        self.assertNotEqual(target.full_name, 'Hacked')
        self.assertNotEqual(target.email, 'x@example.com')

    def test_no_add_or_delete_for_anyone(self) -> None:
        target = self.member()
        for actor in (self.superuser, self.staff('Member Managers')):
            client = self.client_for(actor)
            self.assertEqual(client.get(self.LIST + 'add/').status_code, 403)
            self.assertEqual(client.get(self.url(target).replace('change/', 'delete/')).status_code, 403)
        self.assertTrue(User.objects.filter(pk=target.pk).exists())

    def test_members_anonymous_and_unpermitted_staff_are_blocked(self) -> None:
        target = self.member()
        member_client = self.client_for(self.member())
        self.assertEqual(Client().get(self.LIST).status_code, 302)
        self.assertEqual(member_client.get(self.LIST).status_code, 302)
        self.assertEqual(self.client_for(self.staff()).get(self.LIST).status_code, 403)
        reviewer = self.client_for(self.staff('Membership Reviewers'))
        self.assertEqual(reviewer.get(self.LIST).status_code, 403)
        self.assertEqual(reviewer.get(self.url(target)).status_code, 403)


class AdminSuspensionTests(AdminManagementTestCase):
    def login_member(self, member: User) -> dict:
        return self.login(identifier=member.email)

    def test_suspend_requires_reason_and_changes_nothing_without_it(self) -> None:
        manager, target = self.staff('Member Managers'), self.member()
        response = self.post_user(manager, target, is_active='', suspended_reason='   ')
        target.refresh_from_db()
        self.assertTrue(target.is_active)
        self.assertContains(response, 'A reason is required')

    def test_suspend_stops_every_session_and_login_then_reactivate(self) -> None:
        manager, target = self.staff('Member Managers'), self.member()
        tokens = self.login_member(target)
        self.assertEqual(self.client.get('/auth/profile/get/', HTTP_AUTHORIZATION=f"Bearer {tokens['access']}").status_code, 200)
        self.post_user(manager, target, is_active='', suspended_reason='Fake documents')
        target.refresh_from_db()
        self.assertEqual((target.is_active, target.suspended_reason), (False, 'Fake documents'))
        self.assertIsNotNone(target.suspended_at)
        self.assertEqual(self.client.get('/auth/profile/get/', HTTP_AUTHORIZATION=f"Bearer {tokens['access']}").status_code, 401)
        self.assertEqual(self.post('refresh', {'refresh': tokens['refresh']}).status_code, 401)
        self.assertEqual(self.post('login', {'identifier': target.email, 'password': STRONG_PASSWORD}).status_code, 403)
        self.post_user(manager, target, is_active='on')
        target.refresh_from_db()
        self.assertTrue(target.is_active)
        self.assertEqual(self.post('refresh', {'refresh': tokens['refresh']}).status_code, 401)  # old refresh stays dead
        self.assertIn('access', self.login_member(target))

    def test_suspension_revokes_refresh_tokens_even_if_account_is_re_enabled_another_way(self) -> None:
        """Defence in depth: re-enabling through the shell/DB must not revive old sessions."""
        manager, target = self.staff('Member Managers'), self.member()
        tokens = self.login_member(target)
        self.post_user(manager, target, is_active='', suspended_reason='Fraud')
        User.objects.filter(pk=target.pk).update(is_active=True)
        self.assertEqual(self.post('refresh', {'refresh': tokens['refresh']}).status_code, 401)

    def test_access_token_from_before_a_suspension_stays_dead_after_reactivation(self) -> None:
        """The old 15-minute window: a token issued before the suspension must not work again."""
        manager, target = self.staff('Member Managers'), self.member()
        old = self.login_member(target)
        self.post_user(manager, target, is_active='', suspended_reason='Fraud')
        self.post_user(manager, target, is_active='on')
        target.refresh_from_db()
        self.assertTrue(target.is_active)
        self.assertEqual(target.token_version, 2)
        self.assertEqual(self.client.get('/auth/profile/get/', HTTP_AUTHORIZATION=f"Bearer {old['access']}").status_code, 401)
        fresh = self.login_member(target)
        self.assertEqual(self.client.get('/auth/profile/get/', HTTP_AUTHORIZATION=f"Bearer {fresh['access']}").status_code, 200)

    def test_refresh_token_with_an_old_version_is_rejected_even_if_not_blacklisted(self) -> None:
        target = self.member()
        old = self.login_member(target)
        User.objects.filter(pk=target.pk).update(token_version=5)
        self.assertEqual(self.post('refresh', {'refresh': old['refresh']}).status_code, 401)
        new = self.login_member(target)
        self.assertEqual(self.post('refresh', {'refresh': new['refresh']}).status_code, 200)

    def test_a_refreshed_access_token_keeps_the_current_version(self) -> None:
        target = self.member()
        User.objects.filter(pk=target.pk).update(token_version=3)
        tokens = self.login_member(target)
        rotated = self.post('refresh', {'refresh': tokens['refresh']}).data['data']
        self.assertEqual(self.client.get('/auth/profile/get/', HTTP_AUTHORIZATION=f"Bearer {rotated['access']}").status_code, 200)

    def test_tokens_issued_before_the_field_existed_still_work_until_the_next_change(self) -> None:
        from rest_framework_simplejwt.tokens import RefreshToken

        target = self.member()
        legacy = str(RefreshToken.for_user(target).access_token)   # no token_version claim
        self.assertEqual(self.client.get('/auth/profile/get/', HTTP_AUTHORIZATION=f'Bearer {legacy}').status_code, 200)
        User.objects.filter(pk=target.pk).update(token_version=1)
        self.assertEqual(self.client.get('/auth/profile/get/', HTTP_AUTHORIZATION=f'Bearer {legacy}').status_code, 401)

    def test_token_version_is_not_exposed_or_editable(self) -> None:
        target = self.member()
        profile = self.client.get('/auth/profile/get/', HTTP_AUTHORIZATION=f"Bearer {self.login_member(target)['access']}")
        self.assertNotIn('token', str(profile.data['data']).lower().replace('access', ''))
        self.assertFalse(User._meta.get_field('token_version').editable)

    def test_suspended_referred_member_stops_counting_for_the_referrer(self) -> None:
        manager, referrer, referred = self.staff('Member Managers'), self.member(), self.member()
        Referral.objects.create(referrer=referrer, referred=referred, status='verified')
        self.assertEqual(Referral.verified_count(referrer.user_id), 1)
        self.post_user(manager, referred, is_active='', suspended_reason='Duplicate account')
        self.assertEqual(Referral.verified_count(referrer.user_id), 0)

    def test_cannot_suspend_self(self) -> None:
        manager = self.staff('Member Managers')
        response = self.post_user(manager, manager, is_active='', suspended_reason='oops')
        manager.refresh_from_db()
        self.assertTrue(manager.is_active)
        self.assertContains(response, 'your own account')

    def test_only_superuser_can_suspend_admin_accounts(self) -> None:
        manager = self.staff('Member Managers')
        other_admin = self.staff('Membership Reviewers')
        self.post_user(manager, other_admin, is_active='', suspended_reason='test')
        other_admin.refresh_from_db()
        self.assertTrue(other_admin.is_active)
        self.post_user(self.superuser, other_admin, is_active='', suspended_reason='left the team')
        other_admin.refresh_from_db()
        self.assertFalse(other_admin.is_active)

    def test_staff_without_suspend_permission_cannot_change_status(self) -> None:
        reviewer, target = self.staff('Membership Reviewers'), self.member()
        self.assertEqual(self.client_for(reviewer).get(self.url(target)).status_code, 403)
        view_and_change_only = self.staff()
        view_and_change_only.user_permissions.add(*Permission.objects.filter(codename__in=['view_user', 'change_user']))
        self.post_user(view_and_change_only, target, is_active='', suspended_reason='no right')
        target.refresh_from_db()
        self.assertTrue(target.is_active)

    def test_model_guards_directly(self) -> None:
        actor, target = self.staff('Member Managers'), self.member()
        with self.assertRaises(ValueError):
            target.suspend(actor, ' ')
        with self.assertRaises(ForbiddenError):
            target.suspend(target, 'self')
        with self.assertRaises(ForbiddenError):
            target.suspend(self.staff(), 'no permission')


class AdminAccessManagementTests(AdminManagementTestCase):
    def test_non_superuser_cannot_change_roles_staff_or_groups(self) -> None:
        manager = self.staff('Member Managers')
        target = self.member()
        group = Group.objects.get(name='Member Managers')
        self.post_user(manager, target, role='admin', is_staff='on', is_superuser='on', groups=[group.pk])
        target.refresh_from_db()
        self.assertEqual((target.role, target.is_staff, target.is_superuser, target.groups.count()), ('member', False, False, 0))

    def test_superuser_grants_staff_and_group_then_user_can_work(self) -> None:
        target = self.member()
        group = Group.objects.get(name='Membership Reviewers')
        self.post_user(self.superuser, target, role='admin', is_staff='on', groups=[group.pk])
        target.refresh_from_db()
        self.assertEqual((target.role, target.is_staff), ('admin', True))
        self.assertEqual(list(target.groups.values_list('name', flat=True)), ['Membership Reviewers'])
        client = self.client_for(User.objects.get(pk=target.pk))
        self.assertEqual(client.get('/admin/membership/referral/').status_code, 200)
        self.assertEqual(client.get(self.LIST).status_code, 403)

    def test_superuser_changes_do_not_alter_status_or_level(self) -> None:
        target = self.member(membership_level='active')
        self.post_user(self.superuser, target, role='admin', is_staff='on')
        target.refresh_from_db()
        self.assertEqual((target.is_active, target.membership_level), (True, 'active'))

    def test_group_permissions_are_separated(self) -> None:
        manager = self.client_for(self.staff('Member Managers'))
        reviewer = self.client_for(self.staff('Membership Reviewers'))
        self.assertEqual(manager.get(self.LIST).status_code, 200)
        self.assertEqual(manager.get('/admin/membership/referral/').status_code, 403)
        self.assertEqual(manager.get('/admin/membership/permanentapplication/').status_code, 403)
        self.assertEqual(reviewer.get('/admin/membership/referral/').status_code, 200)
        self.assertEqual(reviewer.get('/admin/membership/permanentapplication/').status_code, 200)
        self.assertEqual(reviewer.get(self.LIST).status_code, 403)


class AdminDashboardTests(AdminManagementTestCase):
    def cards(self, user: User) -> dict[str, int]:
        response = self.client_for(user).get('/admin/')
        self.assertEqual(response.status_code, 200)
        return {c['title']: c['value'] for c in response.context['dashboard_cards']}

    def seed(self) -> None:
        referrer = self.member(membership_level='active', mobile_number='9876543210')
        self.member(membership_level='permanent')
        self.member(is_active=False)
        flagged_user = self.member()
        Referral.objects.create(referrer=referrer, referred=flagged_user, status='flagged')
        PermanentApplication.objects.create(user=referrer, reason='x' * 20)
        ReferralInvite.objects.create(referrer=referrer, full_name='P', email='open@example.com')
        ReferralInvite.objects.create(referrer=referrer, full_name='Q', email='done@example.com', status='registered')

    def test_superuser_sees_all_counts(self) -> None:
        self.seed()
        cards = self.cards(self.superuser)
        self.assertEqual(cards['Members'], 4)
        self.assertEqual((cards['General'], cards['Active'], cards['Permanent'], cards['Suspended']), (2, 1, 1, 1))
        self.assertEqual(cards['Permanent applications to review'], 1)
        self.assertEqual(cards['Flagged referrals to review'], 1)
        self.assertEqual(cards['Open referral invitations'], 1)

    def test_cards_follow_permissions(self) -> None:
        self.seed()
        self.assertEqual(set(self.cards(self.staff('Member Managers'))), {'Members', 'General', 'Active', 'Permanent', 'Suspended'})
        self.assertEqual(
            set(self.cards(self.staff('Membership Reviewers'))),
            {'Permanent applications to review', 'Flagged referrals to review', 'Open referral invitations'},
        )

    def test_dashboard_has_no_personal_data_and_links_to_filtered_lists(self) -> None:
        self.seed()
        response = self.client_for(self.superuser).get('/admin/')
        body = response.content.decode()
        for personal in ('open@example.com', '9876543210', 'Member 1'):
            self.assertNotIn(personal, body)
        self.assertIn('status__exact=flagged', body)
        self.assertIn('is_active__exact=0', body)

    def test_dashboard_requires_staff(self) -> None:
        self.assertEqual(Client().get('/admin/').status_code, 302)
        self.assertEqual(self.client_for(self.member()).get('/admin/').status_code, 302)
