from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import Group, Permission
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from gmp_apps.authentication.models import User
from gmp_apps.schemes.media_check import find_problems, requeue_media
from gmp_apps.schemes.models import Scheme, SchemeImage, SchemeSyncRun

PASSWORD = 'Sunrise#Valley42'
FAST_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
SYNC_NOW = '/admin/schemes/schemesyncrun/sync-now/'
RUNS = '/admin/schemes/schemesyncrun/'
CHECK = '/admin/schemes/scheme/check-media/'
SCHEMES = '/admin/schemes/scheme/'
QUEUE = 'gmp_apps.schemes.admin.sync_schemes.delay'


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class AdminBase(TestCase):
    def setUp(self) -> None:
        cache.clear()
        call_command('setup_admin_groups', stdout=StringIO())
        self.counter = 0
        self.reviewer = self.staff('Scheme Reviewers')

    def staff(self, *groups: str, perms: tuple[str, ...] = ()) -> User:
        self.counter += 1
        user = User.objects.create_user(full_name='Staff', password=PASSWORD, email=f's{self.counter}@example.com', is_staff=True, role='admin', email_verified=True)
        user.groups.add(*Group.objects.filter(name__in=groups))
        for code in perms:
            user.user_permissions.add(Permission.objects.get(codename=code))
        return user

    @staticmethod
    def client_for(user: User | None) -> Client:
        client = Client()
        if user:
            client.force_login(user)
        return client

    @staticmethod
    def messages(response) -> list[str]:
        return [str(m) for m in response.context['messages']]


class SyncNowTests(AdminBase):
    def test_opening_the_page_asks_for_confirmation_and_starts_nothing(self) -> None:
        with mock.patch(QUEUE) as queue:
            response = self.client_for(self.reviewer).get(SYNC_NOW)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Start a scheme sync now?')
        self.assertContains(response, 'csrfmiddlewaretoken')
        queue.assert_not_called()

    def test_posting_queues_exactly_one_sync(self) -> None:
        with mock.patch(QUEUE) as queue:
            response = self.client_for(self.reviewer).post(SYNC_NOW, follow=True)
        queue.assert_called_once_with()
        self.assertEqual(response.redirect_chain[-1][0], RUNS)
        self.assertTrue(any('Sync queued' in m for m in self.messages(response)))

    def test_a_running_sync_blocks_a_second_one(self) -> None:
        SchemeSyncRun.objects.create(status='running')
        with mock.patch(QUEUE) as queue:
            page = self.client_for(self.reviewer).get(SYNC_NOW)
            response = self.client_for(self.reviewer).post(SYNC_NOW, follow=True)
        self.assertContains(page, 'already running')
        queue.assert_not_called()
        self.assertTrue(any('already running' in m for m in self.messages(response)))

    def test_a_stale_running_row_does_not_block(self) -> None:
        run = SchemeSyncRun.objects.create(status='running')
        SchemeSyncRun.objects.filter(pk=run.pk).update(started_date_time=timezone.now() - timedelta(days=2))
        with mock.patch(QUEUE) as queue:
            self.client_for(self.reviewer).post(SYNC_NOW, follow=True)
        queue.assert_called_once_with()

    def test_a_broken_queue_is_a_message_not_a_crash(self) -> None:
        with mock.patch(QUEUE, side_effect=ConnectionError('redis down')):
            response = self.client_for(self.reviewer).post(SYNC_NOW, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any('could not be queued' in m for m in self.messages(response)))
        self.assertFalse(any('redis down' in m for m in self.messages(response)))   # no internals shown

    def test_only_people_with_the_sync_permission_can_use_it(self) -> None:
        viewer = self.staff(perms=('view_schemesyncrun',))
        others = [viewer, self.staff('Support Handlers'), self.staff('Content Publishers'), self.staff('Knowledge Approvers'), self.staff()]
        with mock.patch(QUEUE) as queue:
            for user in others:
                client = self.client_for(user)
                self.assertEqual(client.get(SYNC_NOW).status_code, 403)
                self.assertEqual(client.post(SYNC_NOW).status_code, 403)
            self.assertEqual(Client().post(SYNC_NOW).status_code, 302)       # anonymous: to the login page
            member = Client()
            member.force_login(User.objects.create_user(full_name='M', password=PASSWORD, email='m@example.com', email_verified=True))
            self.assertEqual(member.post(SYNC_NOW).status_code, 302)
            root = User.objects.create_superuser(full_name='Root', password=PASSWORD, email='root@example.com')
            self.assertEqual(self.client_for(root).post(SYNC_NOW).status_code, 302)
        queue.assert_called_once_with()                                      # only the superuser got through

    def test_the_post_needs_a_csrf_token(self) -> None:
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.reviewer)
        with mock.patch(QUEUE) as queue:
            self.assertEqual(client.post(SYNC_NOW).status_code, 403)
        queue.assert_not_called()

    def test_the_button_only_shows_for_those_allowed(self) -> None:
        self.assertContains(self.client_for(self.reviewer).get(RUNS), 'sync-now')
        viewer = self.staff(perms=('view_schemesyncrun',))
        self.assertNotContains(self.client_for(viewer).get(RUNS), 'sync-now')

    def test_the_run_log_stays_read_only_and_shows_duration(self) -> None:
        run = SchemeSyncRun.objects.create(status='success', created=3)
        SchemeSyncRun.objects.filter(pk=run.pk).update(finished_date_time=run.started_date_time + timedelta(seconds=125))
        self.assertContains(self.client_for(self.reviewer).get(RUNS), '2m 5s')
        self.assertEqual(self.client_for(self.reviewer).get(RUNS + 'add/').status_code, 403)
        self.client_for(self.reviewer).post(f'{RUNS}{run.pk}/delete/', {'post': 'yes'})
        self.assertTrue(SchemeSyncRun.objects.filter(pk=run.pk).exists())

    def test_running_run_has_no_duration_yet(self) -> None:
        SchemeSyncRun.objects.create(status='running')
        self.assertEqual(self.client_for(self.reviewer).get(RUNS).status_code, 200)


class MediaAdminTests(AdminBase):
    def owned(self, title: str, synced: bool = True, **extra) -> Scheme:
        return Scheme.objects.create(title=title, source_url=f'https://www.govtschemes.in/{title}', media_synced_at=timezone.now() if synced else None, **extra)

    def test_check_reports_a_clean_state(self) -> None:
        self.owned('fine-one')
        response = self.client_for(self.reviewer).get(CHECK, follow=True)
        self.assertTrue(any('All imported schemes have their pictures' in m for m in self.messages(response)))

    def test_check_reports_unverified_and_missing_files(self) -> None:
        self.owned('waiting-one', synced=False)
        gone = self.owned('gone-files')
        SchemeImage.objects.create(scheme=gone, file='scheme_images/not-there.png', source_url='https://www.govtschemes.in/a.png')
        response = self.client_for(self.reviewer).get(CHECK, follow=True)
        text = ' '.join(self.messages(response))
        self.assertIn('2 scheme(s)', text)
        self.assertIn('waiting-one', text)

    def test_check_changes_nothing_and_is_view_only_permission(self) -> None:
        waiting = self.owned('waiting-two', synced=False)
        viewer = self.staff(perms=('view_scheme',))
        self.assertEqual(self.client_for(viewer).get(CHECK, follow=True).status_code, 200)
        waiting.refresh_from_db()
        self.assertIsNone(waiting.media_synced_at)
        for blocked in (self.staff('Support Handlers'), self.staff('Portal Managers'), self.staff()):
            self.assertEqual(self.client_for(blocked).get(CHECK).status_code, 403)
        self.assertEqual(Client().get(CHECK).status_code, 302)

    def requeue(self, user: User, *schemes: Scheme):
        data = {'action': 'requeue_media_selected', '_selected_action': [s.pk for s in schemes]}
        return self.client_for(user).post(SCHEMES, data, follow=True)

    def test_requeue_marks_only_selected_owned_schemes_and_drops_broken_records(self) -> None:
        target, untouched = self.owned('target-one'), self.owned('untouched-one')
        broken = SchemeImage.objects.create(scheme=target, file='scheme_images/missing.png', source_url='https://www.govtschemes.in/m.png')
        kept = SchemeImage.objects.create(scheme=untouched, file='scheme_images/missing2.png', source_url='https://www.govtschemes.in/m2.png')
        response = self.requeue(self.reviewer, target)
        target.refresh_from_db()
        untouched.refresh_from_db()
        self.assertIsNone(target.media_synced_at)
        self.assertIsNotNone(untouched.media_synced_at)
        self.assertFalse(SchemeImage.objects.filter(pk=broken.pk).exists())
        self.assertTrue(SchemeImage.objects.filter(pk=kept.pk).exists())
        self.assertTrue(any('1 scheme(s)' in m and '1 broken' in m for m in self.messages(response)))

    def test_requeue_leaves_admin_managed_schemes_alone(self) -> None:
        manual = Scheme.objects.create(title='manual-one', is_manual=True, media_synced_at=timezone.now())
        edited = self.owned('edited-one', locally_edited=True)
        response = self.requeue(self.reviewer, manual, edited)
        manual.refresh_from_db(), edited.refresh_from_db()
        self.assertIsNotNone(manual.media_synced_at)
        self.assertIsNotNone(edited.media_synced_at)
        self.assertTrue(any('managed by an admin' in m for m in self.messages(response)))

    def test_requeue_needs_the_change_permission(self) -> None:
        target = self.owned('target-two')
        viewer = self.staff(perms=('view_scheme',))
        self.requeue(viewer, target)
        self.requeue(self.staff('Support Handlers'), target)
        target.refresh_from_db()
        self.assertIsNotNone(target.media_synced_at)

    def test_requeue_function_and_command_share_one_implementation(self) -> None:
        waiting = self.owned('waiting-three', synced=False)
        problems = find_problems()
        self.assertIn(waiting.pk, problems)
        owned, removed = requeue_media(problems)
        self.assertEqual((owned, removed), ({waiting.pk}, 0))
