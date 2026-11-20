import json

from django.db import connection
from django.test.utils import CaptureQueriesContext

from gmp_apps.member_documents.tests import PNG, DocumentBase, unique_pdf, upload
from gmp_apps.member_documents.models import MemberDocument

CARD = '/membership/id_card/get/'


class IdCardTests(DocumentBase):
    """FG7 item 9: the owner's own card data only, nothing sensitive, no public link."""

    def tearDown(self) -> None:
        self.purge_disk()

    def card(self, user=None, **query):
        return self.client_for(user or self.member).get(CARD, query)

    def photo(self, user, data: bytes = PNG, name: str = 'me.png') -> MemberDocument:
        return MemberDocument.add(user, 'profile_photo', upload(name, data + name.encode()))

    def test_the_card_has_exactly_the_allowed_fields_and_the_members_own_values(self) -> None:
        response = self.card()
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data['data']
        self.assertEqual(set(data), {'fullName', 'membershipId', 'membershipLevel', 'memberSince', 'photo'})
        self.assertEqual((data['fullName'], data['membershipId'], data['membershipLevel']),
                         (self.member.full_name, self.member.membership_id, 'general'))
        self.assertIsNone(data['photo'])
        self.assertEqual(data['memberSince'], self.client_for(self.member).get('/auth/profile/get/').data['data']['createdDateTime'])
        theirs = self.card(self.other).data['data']       # each member gets their own card, not the first user's
        self.assertEqual((theirs['fullName'], theirs['membershipId']), (self.other.full_name, self.other.membership_id))

    def test_the_level_follows_the_member(self) -> None:
        type(self.member).objects.filter(pk=self.member.pk).update(membership_level='permanent')
        self.member.refresh_from_db()
        self.assertEqual(self.card().data['data']['membershipLevel'], 'permanent')

    def test_it_never_contains_government_ids_or_contact_details(self) -> None:
        columns = self.member.set_government_id('aadhaar', '234567890123') + self.member.set_government_id('pan', 'ABCDE1234F')
        self.member.house_street = 'secret street'
        self.member.mobile_number = '+919876543210'
        self.member.save()
        self.assertTrue(columns)
        body = json.dumps(self.card().data, default=str)
        for secret in ('234567890123', '0123', 'ABCDE1234F', '234F', self.member.email, '9876543210', 'secret street', 'aadhaar', 'pan'):
            self.assertNotIn(secret, body.replace('panNumber', ''), secret)

    def test_the_photo_is_the_members_own_latest_profile_photo_only(self) -> None:
        self.add(self.member, 'address_proof', unique_pdf('proof'))                 # another type is never the photo
        theirs = self.photo(self.other, name='theirs.png')                           # another member's photo is never shown
        self.assertIsNone(self.card().data['data']['photo'])
        mine = self.photo(self.member)
        photo = self.card().data['data']['photo']
        self.assertEqual(set(photo), {'documentId', 'downloadUrl'})
        self.assertEqual(photo['documentId'], mine.document_id)
        self.assertNotEqual(photo['documentId'], theirs.document_id)
        self.assertTrue(photo['downloadUrl'].endswith(f'?document_id={mine.document_id}'))
        self.assertEqual(self.client_for(self.member).get(photo['downloadUrl']).status_code, 200)
        self.assertEqual(self.client_for(self.other).get(photo['downloadUrl']).status_code, 404)   # the link only works for the owner

    def test_a_user_id_in_the_query_cannot_show_someone_elses_card(self) -> None:
        data = self.card(user_id=self.other.user_id).data['data']
        self.assertEqual(data['membershipId'], self.member.membership_id)
        self.assertNotEqual(data['membershipId'], self.other.membership_id)

    def test_authentication_roles_and_methods(self) -> None:
        self.assertEqual(self.client_for(None).get(CARD).status_code, 401)
        self.assertEqual(self.client_for(self.admin).get(CARD).status_code, 403)
        for method in ('post', 'put', 'patch', 'delete'):
            self.assertEqual(getattr(self.client_for(self.member), method)(CARD, {}, format='json').status_code, 405, method)

    def test_query_count_is_constant(self) -> None:
        def count() -> int:
            with CaptureQueriesContext(connection) as queries:
                self.card()
            return len(queries)

        small = count()
        self.photo(self.member)
        self.assertLessEqual(count(), small + 1)

    def test_swagger_documents_the_endpoint(self) -> None:
        body = self.client_for(None).get('/api/schema/').content.decode()
        self.assertIn('/membership/id_card/get/', body)
        self.assertIn('IdCardResponseGet', body)
