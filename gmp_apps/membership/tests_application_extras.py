from io import StringIO
from pathlib import Path

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from gmp_apps.authentication.models import User
from gmp_apps.member_documents.models import MemberDocument, MemberDocumentAccessLog
from gmp_apps.member_documents.tests import DocumentBase, unique_pdf, upload
from gmp_apps.membership.models import PermanentApplication

APPLY = '/membership/permanent_application/'
REASON = 'I have served the organisation for years and wish to continue'
DOC_BASE = '/member_documents/document/'


class ExtrasBase(DocumentBase):
    def setUp(self) -> None:
        super().setUp()
        User.objects.filter(pk__in=[self.member.pk, self.other.pk]).update(membership_level='active')
        self.member.refresh_from_db()
        self.other.refresh_from_db()
        self.police = self.add(self.member, 'police_verification', unique_pdf('police'), 'police.pdf')
        self.character = self.add(self.member, 'character_certificate', unique_pdf('char'), 'character.pdf')
        self.father = self.add(self.member, 'father_verification', unique_pdf('father'), 'father.pdf')
        self.proof = self.add(self.member, 'address_proof', unique_pdf('proof'), 'proof.pdf')
        self.theirs = self.add(self.other, 'police_verification', unique_pdf('theirs'), 'theirs.pdf')

    def tearDown(self) -> None:
        self.purge_disk()

    def apply(self, user: User | None = None, **extra):
        return self.client_for(user or self.member).post(APPLY + 'create/', {'reason': REASON, **extra}, format='json')

    def get(self, application_id: int, user: User | None = None):
        return self.client_for(user or self.member).get(APPLY + 'get/', {'application_id': application_id})


class ApplyWithExtrasTests(ExtrasBase):
    def test_the_old_request_still_works_and_has_no_extras(self) -> None:
        response = self.apply()
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data['data']
        self.assertEqual((data['declarationAccepted'], data['documents'], data['status']), (False, [], 'pending'))
        self.assertTrue({'applicationId', 'reason', 'status', 'adminRemarks', 'createdDateTime', 'reviewedDateTime'} <= set(data))

    def test_documents_and_the_declaration_are_stored_and_returned_everywhere(self) -> None:
        response = self.apply(document_ids=[self.police.document_id, self.father.document_id], declaration_accepted=True)
        self.assertEqual(response.status_code, 200, response.data)
        application_id = response.data['data']['applicationId']
        for data in (response.data['data'], self.get(application_id).data['data'],
                     self.client_for(self.member).get(APPLY + 'get_all/').data['data']['data'][0]):
            self.assertTrue(data['declarationAccepted'])
            self.assertEqual(sorted(d['documentType'] for d in data['documents']), ['father_verification', 'police_verification'])
            self.assertEqual({d['fileName'] for d in data['documents']}, {'police.pdf', 'father.pdf'})
            self.assertTrue(all(d['downloadUrl'].startswith(DOC_BASE + 'download/?document_id=') for d in data['documents']))
        stored = PermanentApplication.objects.get(pk=application_id)
        self.assertEqual(set(stored.documents.values_list('pk', flat=True)), {self.police.pk, self.father.pk})

    def test_duplicates_are_collapsed_and_all_three_types_are_accepted(self) -> None:
        ids = [self.police.document_id, self.police.document_id, self.character.document_id, self.father.document_id]
        response = self.apply(document_ids=ids)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['data']['documents']), 3)

    def test_only_my_own_verification_documents_can_be_attached(self) -> None:
        refusals = {
            'someone else\'s': [self.theirs.document_id], 'missing': [999999], 'wrong type address_proof': [self.proof.document_id],
            'mixed good and bad': [self.police.document_id, self.theirs.document_id],
        }
        messages = set()
        for label, ids in refusals.items():
            response = self.apply(document_ids=ids)
            self.assertEqual(response.status_code, 400, label)
            messages.add(str(response.data['error']))
        self.assertEqual(len(messages), 1)                                   # one identical refusal: nothing about other members' files leaks
        self.assertEqual(PermanentApplication.objects.count(), 0)
        self.assertEqual(self.theirs.permanent_applications.count(), 0)

    def test_aadhaar_pan_photo_and_other_types_are_not_verification_documents(self) -> None:
        for kind in ('aadhaar', 'pan', 'profile_photo', 'other'):
            document = MemberDocument.add(self.member, kind, upload(f'{kind}.dat', PNG_OR_PDF[kind]))
            self.assertEqual(self.apply(document_ids=[document.document_id]).status_code, 400, kind)
        self.assertEqual(PermanentApplication.objects.count(), 0)

    def test_bad_shapes_are_400(self) -> None:
        for bad in ({'document_ids': 'abc'}, {'document_ids': [0]}, {'document_ids': ['x']}, {'document_ids': list(range(1, 12))}, {'document_ids': [-1]}, {'declaration_accepted': 'maybe'}):
            self.assertEqual(self.apply(**bad).status_code, 400, bad)
        self.assertEqual(self.apply(document_ids=[]).status_code, 200)

    def test_the_list_is_capped_even_when_every_id_is_valid(self) -> None:
        too_many = [self.police.document_id] * 11
        self.assertEqual(self.apply(document_ids=too_many).status_code, 400)
        self.assertEqual(self.apply(document_ids=[self.police.document_id] * 10).status_code, 200)

    def test_the_approval_rules_are_untouched(self) -> None:
        self.assertEqual(self.apply(document_ids=[self.police.document_id], declaration_accepted=True, status='approved', membership_level='permanent', admin_remarks='ok').status_code, 200)
        application = PermanentApplication.objects.get()
        self.member.refresh_from_db()
        self.assertEqual((application.status, application.admin_remarks, self.member.membership_level), ('pending', '', 'active'))   # a member cannot self-approve
        self.assertEqual(self.apply().status_code, 400)                                                                                  # still one pending only
        general = self.make_member()
        self.assertEqual(self.apply(general, document_ids=[]).status_code, 400)                                                         # still Active members only
        PermanentApplication.review(application.pk, self.admin, 'approve')
        self.member.refresh_from_db()
        self.assertEqual(self.member.membership_level, 'permanent')

    def test_an_application_without_documents_or_declaration_can_still_be_approved(self) -> None:
        self.apply()
        application = PermanentApplication.objects.get()
        self.assertFalse(application.declaration_accepted)
        PermanentApplication.review(application.pk, self.admin, 'approve')
        self.assertEqual(PermanentApplication.objects.get().status, 'approved')

    def test_authentication_roles_and_other_members_cannot_see_the_extras(self) -> None:
        application_id = self.apply(document_ids=[self.police.document_id], declaration_accepted=True).data['data']['applicationId']
        self.assertEqual(self.client_for(None).post(APPLY + 'create/', {'reason': REASON}, format='json').status_code, 401)
        self.assertEqual(self.client_for(self.admin).post(APPLY + 'create/', {'reason': REASON}, format='json').status_code, 403)
        spy = self.get(application_id, self.other)
        self.assertEqual(spy.status_code, 404)
        self.assertNotIn('police.pdf', spy.content.decode())
        mine_only = self.client_for(self.other).get(APPLY + 'get_all/').content.decode()
        self.assertNotIn('police.pdf', mine_only)
        self.assertNotIn(str(self.police.document_id) + '&', mine_only)

    def test_the_progress_summary_keeps_its_shape(self) -> None:
        self.apply(document_ids=[self.police.document_id], declaration_accepted=True)
        progress = self.client_for(self.member).get('/membership/progress/get/').data['data']['permanentApplication']
        self.assertEqual(set(progress), {'applicationId', 'status'})

    def test_listing_uses_a_constant_number_of_queries(self) -> None:
        def count() -> int:
            with CaptureQueriesContext(connection) as queries:
                self.client_for(self.member).get(APPLY + 'get_all/', {'limit': 100})
            return len(queries)

        first = self.apply(document_ids=[self.police.document_id]).data['data']['applicationId']
        small = count()
        PermanentApplication.objects.filter(pk=first).update(status='rejected')
        for index, doc in enumerate((self.character, self.father)):
            application = PermanentApplication.objects.create(user=self.member, reason=REASON, status='rejected')
            application.documents.set([doc])
        self.assertEqual(count(), small)

    def test_the_schema_documents_the_new_fields(self) -> None:
        body = self.client_for(None).get('/api/schema/').content.decode()
        for name in ('document_ids', 'declaration_accepted', 'declarationAccepted'):
            self.assertIn(name, body)


class DeletionGuardTests(ExtrasBase):
    def delete(self, document: MemberDocument):
        return self.client_for(self.member).delete(DOC_BASE + 'delete/?document_id=%d' % document.document_id)

    def test_a_document_under_review_cannot_be_deleted(self) -> None:
        self.apply(document_ids=[self.police.document_id])
        response = self.delete(self.police)
        self.assertEqual(response.status_code, 400)
        self.assertIn('under review', str(response.data))
        self.assertTrue(MemberDocument.objects.filter(pk=self.police.pk).exists())
        self.assertTrue(Path(self.root, self.police.file.name).is_file())
        self.assertEqual(self.delete(self.character).status_code, 200)       # an unrelated document is free to go

    def test_after_the_decision_it_can_be_deleted_and_the_application_survives(self) -> None:
        self.apply(document_ids=[self.police.document_id, self.father.document_id])
        application = PermanentApplication.objects.get()
        PermanentApplication.review(application.pk, self.admin, 'reject', 'Incomplete')
        self.assertEqual(self.delete(self.police).status_code, 200)
        data = self.get(application.pk).data['data']
        self.assertEqual([d['documentType'] for d in data['documents']], ['father_verification'])
        self.assertTrue(PermanentApplication.objects.filter(pk=application.pk).exists())

    def test_a_document_freed_by_a_decision_can_be_attached_to_the_next_application(self) -> None:
        self.apply(document_ids=[self.police.document_id])
        PermanentApplication.review(PermanentApplication.objects.get().pk, self.admin, 'reject', 'Please reapply')
        again = self.apply(document_ids=[self.police.document_id])
        self.assertEqual(again.status_code, 200)
        self.assertEqual(self.delete(self.police).status_code, 400)


class AdminExtrasTests(ExtrasBase):
    def setUp(self) -> None:
        super().setUp()
        call_command('setup_admin_groups', stdout=StringIO())
        self.application = PermanentApplication.objects.create(user=self.member, reason=REASON, declaration_accepted=True)
        self.application.documents.set([self.police, self.father])
        self.url = f'/admin/membership/permanentapplication/{self.application.pk}/change/'

    def staff(self, *groups: str) -> User:
        self.counter += 1
        user = User.objects.create_user(full_name='Staff', password='Sunrise#Valley42', email=f'st{self.counter}@example.com', is_staff=True, role='admin', email_verified=True)
        user.groups.add(*Group.objects.filter(name__in=groups))
        return user

    @staticmethod
    def web(user: User) -> Client:
        client = Client()
        client.force_login(user)
        return client

    def test_the_reviewer_sees_the_declaration_and_the_attached_documents(self) -> None:
        page = self.web(self.staff('Membership Reviewers')).get(self.url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Police verification')
        self.assertContains(page, 'police.pdf')
        self.assertContains(page, 'father.pdf')
        self.assertNotContains(page, 'character.pdf')
        self.assertNotContains(page, 'proof.pdf')
        self.assertContains(page, 'no download permission')
        self.assertNotContains(page, '/download/')

    def test_a_reviewer_who_may_download_gets_logged_links(self) -> None:
        reviewer = self.staff('Membership Reviewers', 'Document Reviewers')
        page = self.web(reviewer).get(self.url)
        self.assertContains(page, f'/admin/member_documents/memberdocument/{self.police.pk}/download/')
        self.assertNotContains(page, 'no download permission')
        response = self.web(reviewer).get(f'/admin/member_documents/memberdocument/{self.police.pk}/download/')
        self.assertEqual(response.status_code, 200)
        b''.join(response.streaming_content)
        self.assertEqual(MemberDocumentAccessLog.objects.get().admin_id, reviewer.user_id)

    def test_the_documents_cannot_be_changed_from_the_admin_form(self) -> None:
        reviewer = self.staff('Membership Reviewers')
        self.web(reviewer).post(self.url, {'admin_remarks': 'noted', 'documents': [self.proof.pk], 'declaration_accepted': '', '_save': 'Save'})
        self.application.refresh_from_db()
        self.assertEqual(set(self.application.documents.values_list('pk', flat=True)), {self.police.pk, self.father.pk})
        self.assertTrue(self.application.declaration_accepted)

    def test_staff_without_the_membership_permission_cannot_open_it(self) -> None:
        for user in (self.staff(), self.staff('Document Reviewers'), self.staff('Support Handlers')):
            self.assertEqual(self.web(user).get(self.url).status_code, 403)

    def test_an_application_without_extras_shows_a_plain_page(self) -> None:
        plain = PermanentApplication.objects.create(user=self.other, reason=REASON)
        page = self.web(self.staff('Membership Reviewers')).get(f'/admin/membership/permanentapplication/{plain.pk}/change/')
        self.assertContains(page, 'None attached')


PNG_OR_PDF = {kind: unique_pdf(kind) for kind in ('aadhaar', 'pan', 'other')}
PNG_OR_PDF['profile_photo'] = b'\x89PNG\r\n\x1a\n' + b'\x00' * 30
