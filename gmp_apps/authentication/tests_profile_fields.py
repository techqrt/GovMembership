import json
from io import StringIO
from unittest import mock

from cryptography.fernet import Fernet
from django.contrib.auth.models import Group, Permission
from django.core.cache import cache
from django.core.checks import Error
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from rest_framework.test import APIClient

from gmp.config import Configurations
from gmp_apps.authentication.identity import IdentityUtils
from gmp_apps.authentication.models import GovernmentIdAccessLog, User
from gmp_apps.authentication.tests import AuthBaseTestCase, STRONG_PASSWORD
from gmp_apps.common import field_encryption
from gmp_apps.common.checks import field_encryption_keys_check
from gmp_apps.membership.models import Referral

AADHAAR = '123456789012'
PAN = 'ABCDE1234F'
FULL_SET = {
    'father_name': 'Ramesh Verma', 'profession': 'Teacher', 'area_type': 'urban', 'mandal': 'Central Mandal', 'ward_village': 'Ward 12',
    'house_street': '12 Main Road', 'pin_code': '500001', 'aadhaar_number': AADHAAR, 'pan_number': PAN, 'app_language': 'hi',
}
KEY_A, KEY_B, KEY_C = (Fernet.generate_key().decode() for _ in range(3))


class KeyedBase(AuthBaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.object(Configurations, 'field_encryption_keys', [KEY_A])
        patcher.start()
        self.addCleanup(patcher.stop)

    def profile(self, token: str):
        return self.client.get('/auth/profile/get/', HTTP_AUTHORIZATION=f'Bearer {token}')

    def update(self, token: str, data: dict):
        return self.client.put('/auth/profile/update/', data, format='json', HTTP_AUTHORIZATION=f'Bearer {token}')

    def member_with_token(self, email: str = 'asha@example.com', **extra) -> tuple[User, str]:
        user = self.verified_user(email=email, **extra)
        return user, self.login(email)['access']


class RegistrationFieldTests(KeyedBase):
    def test_every_new_field_is_optional_and_old_payloads_still_work(self) -> None:
        user, token = self.member_with_token()
        data = self.profile(token).data['data']
        for key in ('fatherName', 'profession', 'areaType', 'mandal', 'wardVillage', 'houseStreet', 'pinCode', 'appLanguage'):
            self.assertEqual(data[key], '', key)
        self.assertEqual((data['aadhaarNumber'], data['panNumber'], data['declarationAccepted'], data['declarationAcceptedAt']), (None, None, False, None))
        self.assertEqual(user.aadhaar_encrypted, '')

    def test_registering_with_all_fields_stores_them(self) -> None:
        user, token = self.member_with_token(declaration_accepted=True, **FULL_SET)
        data = self.profile(token).data['data']
        self.assertEqual((data['fatherName'], data['profession'], data['areaType'], data['mandal'], data['wardVillage'], data['houseStreet'], data['pinCode'], data['appLanguage']),
                         ('Ramesh Verma', 'Teacher', 'urban', 'Central Mandal', 'Ward 12', '12 Main Road', '500001', 'hi'))
        self.assertEqual((data['aadhaarNumber'], data['panNumber']), ('XXXXXXXX9012', 'XXXXXX234F'))
        self.assertTrue(data['declarationAccepted'])
        self.assertIsNotNone(data['declarationAcceptedAt'])
        user.refresh_from_db()
        self.assertEqual((user.reveal_government_id('aadhaar'), user.reveal_government_id('pan')), (AADHAAR, PAN))

    def test_the_declaration_is_off_unless_accepted_and_records_when(self) -> None:
        user, _ = self.member_with_token(email='no@example.com')
        self.assertEqual((user.declaration_accepted, user.declaration_accepted_at), (False, None))
        user2, _ = self.member_with_token(email='no2@example.com', declaration_accepted=False)
        self.assertFalse(user2.declaration_accepted)
        user3, _ = self.member_with_token(email='yes@example.com', declaration_accepted=True)
        self.assertTrue(user3.declaration_accepted)
        self.assertIsNotNone(user3.declaration_accepted_at)

    def test_numbers_are_normalised(self) -> None:
        user, _ = self.member_with_token(aadhaar_number='1234 5678-9012', pan_number=' abcde1234f ')
        self.assertEqual((user.reveal_government_id('aadhaar'), user.reveal_government_id('pan')), (AADHAAR, PAN))
        self.assertEqual(self.member_with_token(email='l@example.com', app_language='PT-BR')[0].app_language, 'pt-br')

    def test_invalid_values_are_rejected_and_never_echoed(self) -> None:
        bad = [
            {'aadhaar_number': '12345678901'}, {'aadhaar_number': '1234567890123'}, {'aadhaar_number': 'ABCDEFGHIJKL'}, {'aadhaar_number': '1234 5678'},
            {'pan_number': 'ABCD1234EF'}, {'pan_number': 'ABCDE12345'}, {'pan_number': '1234567890'}, {'pan_number': 'ABCDE1234'},
            {'pin_code': '12345'}, {'pin_code': '1234567'}, {'pin_code': 'ABCDEF'}, {'area_type': 'suburb'},
            {'app_language': 'english'}, {'app_language': 'e'}, {'app_language': 'en_IN!'}, {'father_name': 'x' * 151}, {'profession': 'x' * 101},
            {'house_street': 'x' * 201},
        ]
        for index, extra in enumerate(bad):
            cache.clear()
            response = self.post('register', {'full_name': 'Bad Case', 'email': f'bad{index}@example.com', 'password': STRONG_PASSWORD, **extra})
            self.assertEqual(response.status_code, 400, extra)
            for value in extra.values():
                if len(str(value)) > 8:
                    self.assertNotIn(str(value), json.dumps(response.data), extra)
        self.assertFalse(User.objects.filter(email__startswith='bad').exists())

    def test_without_an_encryption_key_registering_with_an_id_fails_cleanly_and_without_it_still_works(self) -> None:
        with mock.patch.object(Configurations, 'field_encryption_keys', []), mock.patch.object(Configurations, 'debug', False):
            response = self.post('register', {'full_name': 'No Key', 'email': 'nokey@example.com', 'password': STRONG_PASSWORD, 'aadhaar_number': AADHAAR})
            self.assertEqual(response.status_code, 500)
            self.assertNotIn(AADHAAR, json.dumps(response.data))
            self.assertNotIn('FIELD_ENCRYPTION_KEYS', json.dumps(response.data))
            self.assertFalse(User.objects.filter(email='nokey@example.com').exists())   # nothing half-saved
            fine = self.post('register', {'full_name': 'No Id', 'email': 'noid@example.com', 'password': STRONG_PASSWORD})
            self.assertEqual(fine.status_code, 200)


class StorageTests(KeyedBase):
    def test_no_column_holds_a_readable_number_and_the_cipher_text_decrypts(self) -> None:
        user, _ = self.member_with_token(aadhaar_number=AADHAAR, pan_number=PAN)
        row = User.objects.filter(pk=user.pk).values().get()
        for column, value in row.items():
            self.assertNotIn(AADHAAR, str(value), column)
            self.assertNotIn(PAN, str(value), column)
        self.assertEqual((row['aadhaar_last4'], row['pan_last4']), ('9012', '234F'))
        self.assertEqual(field_encryption.decrypt(row['aadhaar_encrypted']), AADHAAR)
        self.assertEqual(row['aadhaar_hash'], field_encryption.blind_index('aadhaar', AADHAAR))
        self.assertEqual(len(row['aadhaar_hash']), 64)

    def test_same_number_gives_the_same_lookup_hash_but_different_cipher_text(self) -> None:
        a, _ = self.member_with_token(email='a@example.com', aadhaar_number=AADHAAR)
        b, _ = self.member_with_token(email='b@example.com', aadhaar_number=AADHAAR)
        self.assertEqual(a.aadhaar_hash, b.aadhaar_hash)
        self.assertNotEqual(a.aadhaar_encrypted, b.aadhaar_encrypted)                 # random IV: ciphertexts never match
        self.assertNotEqual(field_encryption.blind_index('aadhaar', AADHAAR), field_encryption.blind_index('pan', AADHAAR))

    def test_a_wrong_key_cannot_read_and_tampering_is_detected(self) -> None:
        user, _ = self.member_with_token(aadhaar_number=AADHAAR)
        with mock.patch.object(Configurations, 'field_encryption_keys', [KEY_C]), self.assertRaises(field_encryption.DecryptionError):
            user.reveal_government_id('aadhaar')
        user.aadhaar_encrypted = user.aadhaar_encrypted[:-4] + 'AAAA'
        with self.assertRaises(field_encryption.DecryptionError):
            user.reveal_government_id('aadhaar')

    def test_key_rotation_keeps_old_data_readable_and_the_command_moves_it_to_the_new_key(self) -> None:
        user, _ = self.member_with_token(aadhaar_number=AADHAAR, pan_number=PAN)
        old_hash = user.aadhaar_hash
        with mock.patch.object(Configurations, 'field_encryption_keys', [KEY_B, KEY_A]):
            self.assertEqual(User.objects.get(pk=user.pk).reveal_government_id('aadhaar'), AADHAAR)     # old key still decrypts
            out = StringIO()
            call_command('reencrypt_government_ids', '--dry-run', stdout=out)
            self.assertIn('Checked 1 member', out.getvalue())
            before = User.objects.get(pk=user.pk).aadhaar_encrypted
            call_command('reencrypt_government_ids', stdout=out)
            after = User.objects.get(pk=user.pk)
            self.assertNotEqual(after.aadhaar_encrypted, before)
            self.assertEqual(after.aadhaar_hash, old_hash)                         # the lookup hash survives rotation
            self.assertNotIn(AADHAAR + PAN, out.getvalue())
        with mock.patch.object(Configurations, 'field_encryption_keys', [KEY_B]):
            moved = User.objects.get(pk=user.pk)
            self.assertEqual((moved.reveal_government_id('aadhaar'), moved.reveal_government_id('pan')), (AADHAAR, PAN))   # old key no longer needed

    def test_the_command_reports_members_it_cannot_decrypt_without_printing_numbers(self) -> None:
        user, _ = self.member_with_token(aadhaar_number=AADHAAR)
        out = StringIO()
        with mock.patch.object(Configurations, 'field_encryption_keys', [KEY_C]), self.assertRaises(SystemExit):
            call_command('reencrypt_government_ids', stdout=out)
        self.assertIn(user.membership_id, out.getvalue())
        self.assertNotIn(AADHAAR, out.getvalue())

    def test_development_key_is_only_derived_in_debug(self) -> None:
        with mock.patch.object(Configurations, 'field_encryption_keys', []):
            with mock.patch.object(Configurations, 'debug', True):
                self.assertEqual(field_encryption.decrypt(field_encryption.encrypt('x')), 'x')
            with mock.patch.object(Configurations, 'debug', False), self.assertRaises(ImproperlyConfigured):
                field_encryption.encrypt('x')
        with mock.patch.object(Configurations, 'field_encryption_keys', ['not-a-key']), self.assertRaises(ImproperlyConfigured):
            field_encryption.encrypt('x')

    def test_the_deployment_check_demands_a_valid_key(self) -> None:
        with mock.patch.object(Configurations, 'field_encryption_keys', []):
            self.assertEqual([e.id for e in field_encryption_keys_check(None)], ['gmp.E001'])
        with mock.patch.object(Configurations, 'field_encryption_keys', ['bad']):
            self.assertEqual([e.id for e in field_encryption_keys_check(None)], ['gmp.E002'])
        self.assertEqual(field_encryption_keys_check(None), [])
        self.assertIsInstance(Error('x'), Error)

    def test_set_government_id_rules(self) -> None:
        user, _ = self.member_with_token()
        with self.assertRaises(ValueError):
            user.set_government_id('aadhaar', '123')
        with self.assertRaises(ValueError):
            user.set_government_id('passport', AADHAAR)
        user.set_government_id('pan', PAN)
        self.assertEqual(user.masked_id('pan'), 'XXXXXX234F')
        user.set_government_id('pan', '')
        self.assertEqual((user.masked_id('pan'), user.pan_encrypted, user.pan_hash), (None, '', ''))

    def test_mask_shapes(self) -> None:
        self.assertEqual(IdentityUtils.mask('aadhaar', '9012'), 'XXXXXXXX9012')
        self.assertEqual(IdentityUtils.mask('pan', '234F'), 'XXXXXX234F')
        for value in ('XXXXXXXX9012', 'xxxxxxxx9012', 'XXXXXX234F'):
            self.assertTrue(IdentityUtils.is_mask(value), value)
        for value in (AADHAAR, PAN, 'XXXX', '', 'XXXXXXXXXXXX9012'):
            self.assertFalse(IdentityUtils.is_mask(value), value)


class ProfileUpdateTests(KeyedBase):
    def test_update_sets_changes_and_masks(self) -> None:
        user, token = self.member_with_token()
        response = self.update(token, FULL_SET)
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data['data']
        self.assertEqual((data['fatherName'], data['pinCode'], data['appLanguage'], data['aadhaarNumber'], data['panNumber']),
                         ('Ramesh Verma', '500001', 'hi', 'XXXXXXXX9012', 'XXXXXX234F'))
        self.assertNotIn(AADHAAR, response.content.decode())
        self.assertNotIn(PAN, response.content.decode())
        user.refresh_from_db()
        self.assertEqual(user.reveal_government_id('aadhaar'), AADHAAR)

    def test_partial_updates_leave_everything_else_alone(self) -> None:
        user, token = self.member_with_token(**FULL_SET)
        self.update(token, {'profession': 'Doctor'})
        user.refresh_from_db()
        self.assertEqual((user.profession, user.father_name, user.pin_code, user.reveal_government_id('aadhaar')), ('Doctor', 'Ramesh Verma', '500001', AADHAAR))

    def test_blank_clears_but_null_and_an_echoed_mask_change_nothing(self) -> None:
        user, token = self.member_with_token(**FULL_SET)
        self.update(token, {'aadhaar_number': None, 'pan_number': 'XXXXXX234F', 'mandal': None, 'profession': 'Doctor'})
        user.refresh_from_db()
        self.assertEqual((user.reveal_government_id('aadhaar'), user.reveal_government_id('pan'), user.mandal), (AADHAAR, PAN, 'Central Mandal'))
        profile = self.profile(token).data['data']
        echo = self.update(token, {'aadhaar_number': profile['aadhaarNumber'], 'pan_number': profile['panNumber'], 'city': 'Pune'})   # a form re-sending what it was shown
        self.assertEqual(echo.status_code, 200)
        user.refresh_from_db()
        self.assertEqual((user.reveal_government_id('aadhaar'), user.reveal_government_id('pan')), (AADHAAR, PAN))
        self.update(token, {'aadhaar_number': '', 'mandal': '', 'area_type': '', 'pin_code': ''})
        user.refresh_from_db()
        self.assertEqual((user.masked_id('aadhaar'), user.aadhaar_encrypted, user.aadhaar_hash, user.mandal, user.area_type, user.pin_code), (None, '', '', '', '', ''))
        self.assertEqual(user.reveal_government_id('pan'), PAN)

    def test_null_means_not_sent_for_every_optional_field(self) -> None:
        user, token = self.member_with_token(**FULL_SET)
        nulls = {name: None for name in ('father_name', 'profession', 'area_type', 'mandal', 'ward_village', 'house_street', 'pin_code', 'app_language')}
        self.assertEqual(self.update(token, {**nulls, 'aadhaar_number': None, 'pan_number': None, 'city': 'Pune'}).status_code, 200)
        user.refresh_from_db()
        self.assertEqual((user.father_name, user.profession, user.area_type, user.mandal, user.ward_village, user.house_street, user.pin_code, user.app_language),
                         ('Ramesh Verma', 'Teacher', 'urban', 'Central Mandal', 'Ward 12', '12 Main Road', '500001', 'hi'))
        self.assertEqual(user.reveal_government_id('aadhaar'), AADHAAR)

    def test_the_stored_id_columns_are_never_editable_in_a_form(self) -> None:
        for column in ('aadhaar_encrypted', 'aadhaar_last4', 'aadhaar_hash', 'pan_encrypted', 'pan_last4', 'pan_hash', 'token_version'):
            self.assertFalse(User._meta.get_field(column).editable, column)

    def test_changing_a_number_replaces_it(self) -> None:
        user, token = self.member_with_token(aadhaar_number=AADHAAR)
        old_hash = user.aadhaar_hash
        self.update(token, {'aadhaar_number': '999988887777'})
        user.refresh_from_db()
        self.assertEqual((user.reveal_government_id('aadhaar'), user.aadhaar_last4), ('999988887777', '7777'))
        self.assertNotEqual(user.aadhaar_hash, old_hash)

    def test_invalid_updates_are_400_and_change_nothing(self) -> None:
        user, token = self.member_with_token(**FULL_SET)
        for bad in ({'aadhaar_number': '12'}, {'pan_number': 'ABCDE12345'}, {'pin_code': '12'}, {'area_type': 'x'}, {'app_language': 'english'}, {'father_name': 'x' * 200}):
            self.assertEqual(self.update(token, bad).status_code, 400, bad)
        self.assertEqual(self.update(token, {}).status_code, 400)
        user.refresh_from_db()
        self.assertEqual((user.pin_code, user.reveal_government_id('aadhaar')), ('500001', AADHAAR))

    def test_internal_columns_and_other_privileged_fields_cannot_be_set(self) -> None:
        user, token = self.member_with_token()
        self.update(token, {
            'profession': 'x', 'aadhaar_encrypted': 'hack', 'aadhaar_hash': 'hack', 'aadhaar_last4': '0000', 'token_version': 99,
            'membership_level': 'permanent', 'declaration_accepted': True, 'declaration_accepted_at': '2020-01-01T00:00:00Z', 'is_staff': True,
        })
        user.refresh_from_db()
        self.assertEqual((user.aadhaar_encrypted, user.aadhaar_hash, user.aadhaar_last4, user.token_version, user.membership_level, user.declaration_accepted, user.is_staff),
                         ('', '', '', 0, 'general', False, False))

    def test_a_member_only_ever_changes_their_own_numbers(self) -> None:
        mine, my_token = self.member_with_token(email='me@example.com', aadhaar_number=AADHAAR)
        other, _ = self.member_with_token(email='other@example.com', aadhaar_number='555566667777')
        self.update(my_token, {'aadhaar_number': '111122223333', 'user_id': other.user_id})
        other.refresh_from_db()
        self.assertEqual(other.reveal_government_id('aadhaar'), '555566667777')

    def test_anonymous_gets_401(self) -> None:
        self.assertEqual(self.client.put('/auth/profile/update/', {'profession': 'x'}, format='json').status_code, 401)
        self.assertEqual(self.client.get('/auth/profile/get/').status_code, 401)


class NoLeakTests(KeyedBase):
    def test_full_numbers_never_appear_in_any_response_to_anyone(self) -> None:
        owner, owner_token = self.member_with_token(email='owner@example.com', aadhaar_number=AADHAAR, pan_number=PAN, **{k: v for k, v in FULL_SET.items() if k not in ('aadhaar_number', 'pan_number')})
        friend, friend_token = self.member_with_token(email='friend@example.com')
        Referral.objects.create(referrer=friend, referred=owner, status='verified')
        Referral.objects.create(referrer=owner, referred=self.member_with_token(email='third@example.com')[0], status='verified')
        forbidden = [AADHAAR, PAN, owner.aadhaar_encrypted, owner.aadhaar_hash, owner.pan_encrypted, owner.pan_hash, 'aadhaar_encrypted', 'aadhaarEncrypted']
        paths = ['/auth/profile/get/', '/dashboard/get/', '/membership/referral/get_all/', '/membership/progress/get/', '/notifications/get_all/']
        for token in (owner_token, friend_token):
            for path in paths:
                response = self.client.get(path, HTTP_AUTHORIZATION=f'Bearer {token}')
                text = response.content.decode()
                for secret in forbidden:
                    self.assertNotIn(secret, text, f'{path}: {secret[:12]}')
        login = self.post('login', {'identifier': 'owner@example.com', 'password': STRONG_PASSWORD})
        self.assertNotIn(AADHAAR, login.content.decode())
        self.assertEqual(login.data['data']['user']['aadhaarNumber'], 'XXXXXXXX9012')
        friend_view = self.client.get('/membership/referral/get_all/', HTTP_AUTHORIZATION=f'Bearer {friend_token}').content.decode()
        for private in ('9012', '234F', 'Ramesh', '500001', '12 Main Road'):
            self.assertNotIn(private, friend_view, private)          # not even the masked form or any new field reaches another member

    def test_the_api_schema_lists_the_new_fields_as_masked(self) -> None:
        body = APIClient().get('/api/schema/').content.decode()
        for name in ('aadhaarNumber', 'panNumber', 'fatherName', 'appLanguage', 'declarationAccepted', 'aadhaar_number', 'declaration_accepted'):
            self.assertIn(name, body, name)
        self.assertNotIn('aadhaarEncrypted', body)
        self.assertNotIn('aadhaar_hash', body)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AdminIdentityTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        call_command('setup_admin_groups', stdout=StringIO())
        patcher = mock.patch.object(Configurations, 'field_encryption_keys', [KEY_A])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.counter = 0
        self.member = User.objects.create_user(full_name='Asha Verma', password=STRONG_PASSWORD, email='asha@example.com', email_verified=True)
        self.member.set_government_id('aadhaar', AADHAAR)
        self.member.set_government_id('pan', PAN)
        self.member.father_name = 'Ramesh Verma'
        self.member.save()
        self.empty_member = User.objects.create_user(full_name='Bina Rao', password=STRONG_PASSWORD, email='bina@example.com', email_verified=True)
        self.reviewer = self.staff('Identity Reviewers')
        self.base = f'/admin/authentication/user/{self.member.pk}/'

    def staff(self, *groups: str, perms: tuple[str, ...] = ()) -> User:
        self.counter += 1
        user = User.objects.create_user(full_name='Staff', password=STRONG_PASSWORD, email=f'staff{self.counter}@example.com', is_staff=True, role='admin', email_verified=True)
        user.groups.add(*Group.objects.filter(name__in=groups))
        for code in perms:
            user.user_permissions.add(Permission.objects.get(codename=code))
        return user

    @staticmethod
    def web(user: User | None) -> Client:
        client = Client()
        if user:
            client.force_login(user)
        return client

    def test_the_member_page_and_lists_show_only_masks_even_to_a_superuser(self) -> None:
        root = User.objects.create_superuser(full_name='Root', password=STRONG_PASSWORD, email='root@example.com')
        for user in (self.reviewer, self.staff('Member Managers'), root):
            for path in (self.base + 'change/', '/admin/authentication/user/'):
                html = self.web(user).get(path).content.decode()
                for secret in (AADHAAR, PAN, self.member.aadhaar_encrypted, self.member.aadhaar_hash):
                    self.assertNotIn(secret, html, path)
            page = self.web(user).get(self.base + 'change/')
            self.assertContains(page, 'XXXXXXXX9012')
            self.assertContains(page, 'XXXXXX234F')
            self.assertContains(page, 'Ramesh Verma')

    def test_the_reveal_page_asks_first_then_shows_and_logs(self) -> None:
        client = self.web(self.reviewer)
        url = self.base + 'government_ids/'
        page = client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Show full numbers')
        self.assertNotContains(page, AADHAAR)
        self.assertEqual(GovernmentIdAccessLog.objects.count(), 0)
        shown = client.post(url)
        self.assertContains(shown, AADHAAR)
        self.assertContains(shown, PAN)
        self.assertIn('no-store', shown['Cache-Control'])
        logs = list(GovernmentIdAccessLog.objects.order_by('log_id'))
        self.assertEqual([(l.action, l.admin_id, l.member_id) for l in logs],
                         [('reveal_aadhaar', self.reviewer.user_id, self.member.user_id), ('reveal_pan', self.reviewer.user_id, self.member.user_id)])

    def test_only_numbers_that_exist_are_logged(self) -> None:
        self.member.set_government_id('pan', '')
        self.member.save()
        self.web(self.reviewer).post(self.base + 'government_ids/')
        self.assertEqual(list(GovernmentIdAccessLog.objects.values_list('action', flat=True)), ['reveal_aadhaar'])
        GovernmentIdAccessLog.objects.all().delete()
        self.web(self.reviewer).post(f'/admin/authentication/user/{self.empty_member.pk}/government_ids/')
        self.assertEqual(GovernmentIdAccessLog.objects.count(), 0)

    def test_people_without_the_permission_cannot_reveal_and_nothing_is_logged(self) -> None:
        for user in (self.staff(), self.staff('Member Managers'), self.staff('Support Handlers'), self.staff('Document Reviewers'), self.staff(perms=('view_user', 'change_user'))):
            client = self.web(user)
            self.assertEqual(client.get(self.base + 'government_ids/').status_code, 403)
            response = client.post(self.base + 'government_ids/')
            self.assertEqual(response.status_code, 403)
            self.assertNotIn(AADHAAR, response.content.decode())
        self.assertEqual(self.web(None).post(self.base + 'government_ids/').status_code, 302)
        member_client = Client()
        member_client.force_login(self.empty_member)
        self.assertEqual(member_client.post(self.base + 'government_ids/').status_code, 302)
        self.assertEqual(self.web(self.reviewer).get('/admin/authentication/user/999999/government_ids/').status_code, 404)
        self.assertEqual(GovernmentIdAccessLog.objects.count(), 0)

    def test_the_reveal_link_shows_only_for_those_allowed_and_only_when_a_number_exists(self) -> None:
        self.assertContains(self.web(self.reviewer).get(self.base + 'change/'), 'government_ids')
        self.assertNotContains(self.web(self.reviewer).get(f'/admin/authentication/user/{self.empty_member.pk}/change/'), 'government_ids/')

    def test_a_number_that_cannot_be_decrypted_is_a_message_not_a_crash(self) -> None:
        with mock.patch.object(Configurations, 'field_encryption_keys', [KEY_C]):
            response = self.web(self.reviewer).post(self.base + 'government_ids/')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, AADHAAR)
        self.assertEqual(GovernmentIdAccessLog.objects.count(), 0)

    def test_search_by_full_number_needs_the_permission_and_is_logged(self) -> None:
        url = '/admin/authentication/user/?q='
        found = self.web(self.reviewer).get(url + '1234 5678 9012')
        self.assertContains(found, self.member.membership_id)
        self.assertNotContains(found, self.empty_member.membership_id)
        self.assertEqual(GovernmentIdAccessLog.objects.get().action, 'search_aadhaar')
        self.assertContains(self.web(self.reviewer).get(url + 'abcde1234f'), self.member.membership_id)
        self.assertEqual(GovernmentIdAccessLog.objects.filter(action='search_pan').count(), 1)
        GovernmentIdAccessLog.objects.all().delete()
        for term in ('XXXXXXXX9012', '9012', '123456789013', 'ABCDE1234G'):
            self.assertNotContains(self.web(self.reviewer).get(url + term), self.member.membership_id, msg_prefix=term)
        manager = self.staff('Member Managers')
        self.assertNotContains(self.web(manager).get(url + AADHAAR), self.member.membership_id)
        self.assertEqual(GovernmentIdAccessLog.objects.filter(admin=manager).count(), 0)

    def test_ordinary_search_still_works_for_everyone(self) -> None:
        manager = self.staff('Member Managers')
        self.assertContains(self.web(manager).get('/admin/authentication/user/?q=Asha'), self.member.membership_id)
        self.assertContains(self.web(self.reviewer).get('/admin/authentication/user/?q=Asha'), self.member.membership_id)

    def test_the_access_log_is_superuser_only_and_read_only(self) -> None:
        self.web(self.reviewer).post(self.base + 'government_ids/')
        logs = '/admin/authentication/governmentidaccesslog/'
        self.assertEqual(self.web(self.reviewer).get(logs).status_code, 403)
        root = User.objects.create_superuser(full_name='Root', password=STRONG_PASSWORD, email='root2@example.com')
        self.assertContains(self.web(root).get(logs), 'reveal_aadhaar')
        self.assertEqual(self.web(root).get(logs + 'add/').status_code, 403)
        log = GovernmentIdAccessLog.objects.first()
        self.web(root).post(f'{logs}{log.pk}/delete/', {'post': 'yes'})
        self.assertTrue(GovernmentIdAccessLog.objects.filter(pk=log.pk).exists())

    def test_member_managers_still_cannot_edit_profile_data(self) -> None:
        manager = self.staff('Member Managers')
        self.web(manager).post(self.base + 'change/', {'father_name': 'Tampered', 'aadhaar_encrypted': 'x', '_save': 'Save'})
        self.member.refresh_from_db()
        self.assertEqual(self.member.father_name, 'Ramesh Verma')
        self.assertEqual(self.member.reveal_government_id('aadhaar'), AADHAAR)

    def test_group_has_exactly_view_user_and_the_reveal_permission(self) -> None:
        codes = set(Group.objects.get(name='Identity Reviewers').permissions.values_list('codename', flat=True))
        self.assertEqual(codes, {'view_user', 'view_government_ids'})
