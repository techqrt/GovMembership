from io import StringIO
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from gmp.config import Configurations
from gmp_apps.authentication.models import User
from gmp_apps.contact_admin.models import ContactCategory, ContactRequest
from gmp_apps.member_documents.models import DocumentType, MemberDocument, MemberDocumentAccessLog
from gmp_apps.member_documents.tests import DocumentBase, unique_pdf, upload

BASE = '/contact_admin/request/'
DOCS = '/member_documents/document/'


class ContactExtrasBase(DocumentBase):
    def setUp(self) -> None:
        super().setUp()
        self.category = ContactCategory.objects.filter(is_active=True).first()
        self.file_a = self.add(self.member, 'contact_attachment', unique_pdf('a'), 'screenshot.pdf')
        self.file_b = self.add(self.member, 'contact_attachment', unique_pdf('b'), 'letter.pdf')
        self.file_c = self.add(self.member, 'contact_attachment', unique_pdf('c'), 'bill.pdf')
        self.theirs = self.add(self.other, 'contact_attachment', unique_pdf('theirs'), 'theirs.pdf')
        self.proof = self.add(self.member, 'address_proof', unique_pdf('proof'), 'proof.pdf')

    def tearDown(self) -> None:
        self.purge_disk()

    def send(self, user: User | None = None, **extra):
        data = {'category_id': self.category.category_id, 'subject': 'Help needed', 'description': 'Please look into my membership problem', **extra}
        cache.clear()
        return self.client_for(user or self.member).post(BASE + 'create/', data, format='json')

    def get(self, request_id: int, user: User | None = None):
        return self.client_for(user or self.member).get(BASE + 'get/', {'request_id': request_id})


class PriorityTests(ContactExtrasBase):
    def test_priority_defaults_to_normal_and_old_requests_still_work(self) -> None:
        response = self.send()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((response.data['data']['priority'], response.data['data']['attachments']), ('normal', []))
        self.assertEqual(ContactRequest.objects.get().priority, 'normal')

    def test_the_member_can_choose_low_normal_or_high(self) -> None:
        for priority in ('low', 'high', 'normal'):
            ContactRequest.objects.all().delete()
            response = self.send(priority=priority)
            self.assertEqual(response.data['data']['priority'], priority)
            self.assertEqual(self.get(response.data['data']['requestId']).data['data']['priority'], priority)

    def test_unknown_priorities_are_refused(self) -> None:
        for bad in ('urgent', 'HIGH', '', 'critical', 1, None, ['high']):
            self.assertEqual(self.send(priority=bad).status_code, 400, repr(bad))
        self.assertEqual(ContactRequest.objects.count(), 0)

    def test_the_list_can_be_filtered_by_priority(self) -> None:
        for priority in ('low', 'high', 'high'):
            ContactRequest.objects.filter(status='resolved').delete()
            item = self.send(priority=priority).data['data']['requestId']
            ContactRequest.objects.filter(pk=item).update(status='resolved')     # keep the open-request cap out of the way
        high = self.client_for(self.member).get(BASE + 'get_all/', {'filter_key': 'priority', 'filter_value': 'high'})
        self.assertEqual(high.status_code, 200)
        self.assertEqual([r['priority'] for r in high.data['data']['data']], ['high'])
        nothing = self.client_for(self.member).get(BASE + 'get_all/', {'filter_key': 'priority', 'filter_value': 'urgent'})
        self.assertEqual((nothing.status_code, nothing.data['data']['data']), (200, []))      # same as the status filter: no match, not an error
        self.assertEqual(self.client_for(self.member).get(BASE + 'get_all/', {'filter_key': 'internal', 'filter_value': 'x'}).status_code, 400)

    def test_a_member_sees_only_their_own_requests_and_priorities(self) -> None:
        mine = self.send(priority='high').data['data']['requestId']
        self.assertEqual(self.get(mine, self.other).status_code, 404)
        self.assertEqual(self.client_for(self.other).get(BASE + 'get_all/').data['data']['data'], [])


class AttachmentTests(ContactExtrasBase):
    def test_a_request_with_attachments(self) -> None:
        response = self.send(attachment_ids=[self.file_a.document_id, self.file_b.document_id])
        self.assertEqual(response.status_code, 200, response.data)
        for data in (response.data['data'], self.get(response.data['data']['requestId']).data['data'],
                     self.client_for(self.member).get(BASE + 'get_all/').data['data']['data'][0]):
            self.assertEqual({d['fileName'] for d in data['attachments']}, {'screenshot.pdf', 'letter.pdf'})
            self.assertTrue(all(d['downloadUrl'].startswith(DOCS + 'download/?document_id=') for d in data['attachments']))
            self.assertTrue(all(d['documentType'] == 'contact_attachment' for d in data['attachments']))

    def test_at_most_three_attachments(self) -> None:
        extra = self.add(self.member, 'contact_attachment', unique_pdf('d'), 'd.pdf')
        four = [self.file_a.document_id, self.file_b.document_id, self.file_c.document_id, extra.document_id]
        self.assertEqual(self.send(attachment_ids=four).status_code, 400)
        self.assertEqual(self.send(attachment_ids=four[:3]).status_code, 200)
        self.assertEqual(self.send(attachment_ids=[self.file_a.document_id] * 4).status_code, 400)

    def test_duplicates_are_collapsed(self) -> None:
        response = self.send(attachment_ids=[self.file_a.document_id] * 3)
        self.assertEqual(len(response.data['data']['attachments']), 1)

    def test_only_my_own_contact_attachments_can_be_attached_with_one_identical_refusal(self) -> None:
        refusals = {'foreign': [self.theirs.document_id], 'missing': [999999], 'wrong type': [self.proof.document_id],
                    'mixed': [self.file_a.document_id, self.theirs.document_id]}
        messages = set()
        for label, ids in refusals.items():
            response = self.send(attachment_ids=ids)
            self.assertEqual(response.status_code, 400, label)
            messages.add(str(response.data['error']))
        self.assertEqual(len(messages), 1)
        self.assertEqual(ContactRequest.objects.count(), 0)                 # nothing created, no daily allowance used
        self.assertEqual(self.theirs.contact_requests.count(), 0)

    def test_bad_shapes_are_400(self) -> None:
        for bad in ('abc', [0], ['x'], [-1]):
            self.assertEqual(self.send(attachment_ids=bad).status_code, 400, bad)
        self.assertEqual(self.send(attachment_ids=[]).status_code, 200)

    def test_a_refused_request_does_not_link_anything(self) -> None:
        with mock.patch.object(Configurations, 'contact_max_open_requests', 0):
            response = self.send(attachment_ids=[self.file_a.document_id])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.file_a.contact_requests.count(), 0)

    def test_other_members_never_see_the_files_of_a_request(self) -> None:
        request_id = self.send(attachment_ids=[self.file_a.document_id]).data['data']['requestId']
        spy = self.get(request_id, self.other)
        self.assertEqual(spy.status_code, 404)
        self.assertNotIn('screenshot.pdf', spy.content.decode())
        self.assertNotIn('screenshot.pdf', self.client_for(self.other).get(BASE + 'get_all/').content.decode())
        self.assertEqual(self.client_for(self.other).get(DOCS + 'download/', {'document_id': self.file_a.document_id}).status_code, 404)

    def test_authentication_and_roles(self) -> None:
        body = {'category_id': self.category.category_id, 'subject': 'Help needed', 'description': 'Please look into this', 'attachment_ids': []}
        self.assertEqual(self.client_for(None).post(BASE + 'create/', body, format='json').status_code, 401)
        self.assertEqual(self.client_for(self.admin).post(BASE + 'create/', body, format='json').status_code, 403)

    def test_contact_attachments_have_their_own_larger_limit_and_a_larger_total(self) -> None:
        member = self.make_member()
        for index in range(15):
            cache.clear()
            self.assertEqual(self.post('contact_attachment', upload(f'f{index}.pdf', unique_pdf(f'cap{index}')), user=member).status_code, 200, index)
        cache.clear()
        over = self.post('contact_attachment', upload('x.pdf', unique_pdf('x')), user=member)
        self.assertEqual(over.status_code, 400)
        self.assertIn('limit for this document type', str(over.data))
        cache.clear()
        self.assertEqual(self.post('pan', upload('pan.pdf', unique_pdf('pan')), user=member).status_code, 200)   # other types still have room
        with mock.patch.object(Configurations, 'member_document_max_contact_attachments', 1):
            fresh = self.make_member()
            cache.clear()
            self.assertEqual(self.post('contact_attachment', upload('1.pdf', unique_pdf('one')), user=fresh).status_code, 200)
            cache.clear()
            self.assertEqual(self.post('contact_attachment', upload('2.pdf', unique_pdf('two')), user=fresh).status_code, 400)
        self.assertEqual(Configurations.member_document_max_per_member, 30)

    def test_the_safety_rules_apply_to_attachments_too(self) -> None:
        for name, data in (('a.html', b'hi'), ('a.exe', b'hi'), ('ok.pdf', b'<html><script>x</script>')):
            cache.clear()
            self.assertEqual(self.post('contact_attachment', upload(name, data)).status_code, 400, name)

    def test_the_listing_uses_a_constant_number_of_queries(self) -> None:
        def count() -> int:
            with CaptureQueriesContext(connection) as queries:
                self.client_for(self.member).get(BASE + 'get_all/', {'limit': 100})
            return len(queries)

        first = self.send(attachment_ids=[self.file_a.document_id]).data['data']['requestId']
        small = count()
        ContactRequest.objects.filter(pk=first).update(status='resolved')
        for file in (self.file_b, self.file_c):
            request = ContactRequest.objects.create(user=self.member, category=self.category, subject='s' * 5, description='d' * 12, status='resolved')
            request.attachments.set([file])
        self.assertEqual(count(), small)


class DeletionGuardTests(ContactExtrasBase):
    def delete(self, document: MemberDocument):
        return self.client_for(self.member).delete(DOCS + 'delete/?document_id=%d' % document.document_id)

    def test_a_file_on_an_open_or_in_progress_request_cannot_be_deleted(self) -> None:
        request_id = self.send(attachment_ids=[self.file_a.document_id]).data['data']['requestId']
        for status in ('open', 'in_progress'):
            ContactRequest.objects.filter(pk=request_id).update(status=status)
            response = self.delete(self.file_a)
            self.assertEqual(response.status_code, 400, status)
            self.assertIn('still handling', str(response.data))
        self.assertTrue(Path(self.root, self.file_a.file.name).is_file())
        self.assertEqual(self.delete(self.file_b).status_code, 200)

    def test_once_resolved_or_closed_the_file_can_be_deleted(self) -> None:
        for status in ('resolved', 'closed'):
            document = self.add(self.member, 'contact_attachment', unique_pdf(status), f'{status}.pdf')
            request = ContactRequest.objects.create(user=self.member, category=self.category, subject='Subject', description='Long enough text here', status=status)
            request.attachments.set([document])
            self.assertEqual(self.delete(document).status_code, 200, status)
            self.assertTrue(ContactRequest.objects.filter(pk=request.pk).exists())
            self.assertEqual(request.attachments.count(), 0)


class AdminTests(ContactExtrasBase):
    def setUp(self) -> None:
        super().setUp()
        call_command('setup_admin_groups', stdout=StringIO())
        self.request_obj = ContactRequest.objects.create(
            user=self.member, category=self.category, subject='Broken page', description='The page does not open for me', priority='high',
        )
        self.request_obj.attachments.set([self.file_a, self.file_b])
        self.url = f'/admin/contact_admin/contactrequest/{self.request_obj.pk}/change/'

    def staff(self, *groups: str) -> User:
        self.counter += 1
        user = User.objects.create_user(full_name='Staff', password='Sunrise#Valley42', email=f'cs{self.counter}@example.com', is_staff=True, role='admin', email_verified=True)
        user.groups.add(*Group.objects.filter(name__in=groups))
        return user

    @staticmethod
    def web(user: User) -> Client:
        client = Client()
        client.force_login(user)
        return client

    def test_the_handler_sees_priority_and_the_attached_files(self) -> None:
        handler = self.staff('Support Handlers')
        page = self.web(handler).get(self.url)
        self.assertContains(page, 'screenshot.pdf')
        self.assertContains(page, 'letter.pdf')
        self.assertNotContains(page, 'bill.pdf')
        self.assertContains(page, 'High')
        self.assertContains(page, 'no download permission')
        self.assertNotContains(page, '/download/')
        listing = self.web(handler).get('/admin/contact_admin/contactrequest/?priority__exact=high')
        self.assertContains(listing, 'Broken page')
        self.assertIn('priority', [spec.field_path for spec in listing.context['cl'].filter_specs])     # the filter is offered, not just accepted
        self.assertNotContains(self.web(handler).get('/admin/contact_admin/contactrequest/?priority__exact=low'), 'Broken page')

    def test_a_handler_who_may_download_gets_logged_links(self) -> None:
        handler = self.staff('Support Handlers', 'Document Reviewers')
        page = self.web(handler).get(self.url)
        self.assertContains(page, f'/admin/member_documents/memberdocument/{self.file_a.pk}/download/')
        response = self.web(handler).get(f'/admin/member_documents/memberdocument/{self.file_a.pk}/download/')
        b''.join(response.streaming_content)
        self.assertEqual(MemberDocumentAccessLog.objects.get().document_id, self.file_a.pk)

    def test_the_admin_cannot_change_the_priority_or_the_files(self) -> None:
        handler = self.staff('Support Handlers')
        self.web(handler).post(self.url, {'status': 'in_progress', 'admin_reply': 'Looking', 'priority': 'low', 'attachments': [self.file_c.pk], '_save': 'Save'})
        self.request_obj.refresh_from_db()
        self.assertEqual((self.request_obj.priority, self.request_obj.status), ('high', 'in_progress'))
        self.assertEqual(set(self.request_obj.attachments.values_list('pk', flat=True)), {self.file_a.pk, self.file_b.pk})

    def test_staff_without_support_permissions_are_refused(self) -> None:
        for user in (self.staff(), self.staff('Document Reviewers'), self.staff('Portal Managers')):
            self.assertEqual(self.web(user).get(self.url).status_code, 403)

    def test_a_request_without_files_shows_none(self) -> None:
        plain = ContactRequest.objects.create(user=self.other, category=self.category, subject='Plain one', description='Nothing attached to this')
        page = self.web(self.staff('Support Handlers')).get(f'/admin/contact_admin/contactrequest/{plain.pk}/change/')
        self.assertContains(page, 'Plain one')


class SchemaTests(ContactExtrasBase):
    def test_the_schema_lists_the_new_fields(self) -> None:
        body = self.client_for(None).get('/api/schema/').content.decode()
        for name in ('attachment_ids', 'priority', 'attachments', 'contact_attachment'):
            self.assertIn(name, body)
        self.assertIn(DocumentType.CONTACT_ATTACHMENT, DocumentType.values)
