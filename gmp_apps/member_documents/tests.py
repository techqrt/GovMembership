import shutil
import tempfile
from io import BytesIO, StringIO
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from rest_framework.test import APIClient

from gmp.config import Configurations
from gmp_apps.authentication.models import User
from gmp_apps.common.private_storage import PrivateStorage
from gmp_apps.member_documents import files
from gmp_apps.member_documents.models import MemberDocument, MemberDocumentAccessLog
from gmp_apps.member_documents.throttles import DocumentUploadThrottle

PASSWORD = 'Sunrise#Valley42'
FAST_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
BASE = '/member_documents/document/'
PDF = b'%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n'
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR' + b'\x00' * 20
JPG = b'\xff\xd8\xff\xe0' + b'\x00' * 30


def upload(name: str, data: bytes, content_type: str = 'application/octet-stream') -> SimpleUploadedFile:
    return SimpleUploadedFile(name, data, content_type=content_type)


def unique_pdf(tag: str) -> bytes:
    return PDF + tag.encode()


# ======================================================================== pure helpers

class FileRuleTests(TestCase):
    def test_dangerous_names_are_refused_in_any_part_and_any_case(self) -> None:
        for name in ('a.html', 'a.HTM', 'a.svg', 'a.js', 'a.exe', 'a.sh', 'a.bat', 'a.php', 'a.php5', 'a.phtml', 'a.jar', 'a.msi', 'a.ps1',
                     'a.xml', 'a.hta', 'a.py', 'a.asp', 'a.jsp', 'a.cmd', 'a.com', 'a.scr', 'a.vbs', 'a.lnk', 'a.dll',
                     'invoice.php.jpg', 'x.html.pdf', 'x.EXE.png', 'C:\\temp\\evil.exe', '../../evil.js', 'a.pdf.sh', 'a.svgz', 'a. php'):
            self.assertTrue(files.has_denied_extension(name), name)
        for name in ('scan.pdf', 'photo.JPG', 'proof.png', 'letter.docx', 'notes.txt', 'data.csv', 'archive.zip', 'noextension', 'my.report.final.pdf', ''):
            self.assertFalse(files.has_denied_extension(name), name)

    def test_dangerous_content_is_found_by_its_bytes(self) -> None:
        dangerous = [
            b'<html><body>x</body></html>', b'  \n\t<!DOCTYPE html><p>', b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', b'<?xml version="1.0"?><x/>',
            b'<?php echo 1;', b'<script>alert(1)</script>', b'#!/bin/sh\nrm -rf /', b'#!/usr/bin/env python', b'MZ\x90\x00\x03' + b'\x00' * 10,
            b'\x7fELF\x02\x01', b'\xfe\xed\xfa\xcf' + b'\x00' * 8, b'\xca\xfe\xba\xbe\x00\x00', b'\xef\xbb\xbf<html>', b'\x00\x00<HTML>',
            '<html><script>x</script>'.encode('utf-16'), b'random header bytes ' + b'x' * 100 + b'<script>alert(1)</script>', b'GARBAGE <iframe src=x>',
            b'<%= 1 %>', b'<body onload=x>',
        ]
        for data in dangerous:
            self.assertTrue(files.has_dangerous_content(data), data[:30])

    def test_ordinary_files_are_not_flagged(self) -> None:
        ordinary = [PDF, PNG, JPG, b'GIF89a' + b'\x00' * 20, b'RIFF\x00\x00\x00\x00WEBPVP8 ', b'plain text notes about my address\n', b'name,phone\nAsha,123\n',
                    b'PK\x03\x04' + b'\x00' * 30, b'\x00\x01\x02\x03' * 50, b'a < b and c > d', b'']
        for data in ordinary:
            self.assertFalse(files.has_dangerous_content(data), data[:20])
        self.assertFalse(files.has_dangerous_content(PDF + b'<script>inside a real pdf stream</script>'))   # a real PDF is judged by its signature

    def test_type_comes_from_the_bytes(self) -> None:
        self.assertEqual(files.sniff_type(PDF), ('pdf', 'application/pdf'))
        self.assertEqual(files.sniff_type(PNG), ('png', 'image/png'))
        self.assertEqual(files.sniff_type(JPG), ('jpg', 'image/jpeg'))
        self.assertEqual(files.sniff_type(b'GIF87a....')[0], 'gif')
        self.assertEqual(files.sniff_type(b'RIFF1234WEBPxxxx')[0], 'webp')
        self.assertEqual(files.sniff_type(b'hello'), ('dat', 'application/octet-stream'))
        self.assertTrue(files.is_image('image/png'))
        self.assertFalse(files.is_image('application/pdf'))

    def test_download_names_are_harmless(self) -> None:
        self.assertEqual(files.display_name('Aadhaar front.pdf', 'pdf'), 'Aadhaar front.pdf')
        self.assertEqual(files.display_name('../../etc/passwd', 'dat'), 'passwd.dat')
        self.assertEqual(files.display_name('C:\\Users\\x\\scan.png', 'png'), 'scan.png')
        self.assertEqual(files.display_name('<script>.pdf', 'pdf'), 'script.pdf')
        self.assertEqual(files.display_name('', 'pdf'), 'document.pdf')
        self.assertEqual(files.display_name('...', 'pdf'), 'document.pdf')
        self.assertEqual(files.display_name('नाम.pdf', 'pdf'), 'document.pdf')
        self.assertEqual(files.display_name('x' * 500 + '.pdf', 'pdf')[-4:], '.pdf')
        self.assertLessEqual(len(files.display_name('x' * 500 + '.pdf', 'pdf')), files.MAX_NAME_LENGTH)
        self.assertNotIn('\n', files.display_name('a\r\nSet-Cookie: x.pdf', 'pdf'))

    def test_attachment_headers(self) -> None:
        response = files.attachment_response(BytesIO(b'x'), 'a.pdf')
        self.assertEqual(response['Content-Type'], 'application/octet-stream')
        self.assertTrue(response['Content-Disposition'].startswith('attachment'))
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertIn('sandbox', response['Content-Security-Policy'])
        self.assertIn('no-store', response['Cache-Control'])


# ======================================================================== API

@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class DocumentBase(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.root = tempfile.mkdtemp(prefix='gmp-private-test-')
        cls.field = MemberDocument._meta.get_field('file')
        cls.original_storage = cls.field.storage
        cls.field.storage = FileSystemStorage(location=cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.field.storage = cls.original_storage
        shutil.rmtree(cls.root, ignore_errors=True)
        super().tearDownClass()

    def setUp(self) -> None:
        cache.clear()
        self.counter = 0
        self.member = self.make_member()
        self.other = self.make_member()
        self.admin = User.objects.create_user(full_name='Admin', password=PASSWORD, email='admin@example.com', role='admin', is_staff=True, email_verified=True)

    def make_member(self) -> User:
        self.counter += 1
        return User.objects.create_user(full_name=f'Asha Verma{self.counter}', password=PASSWORD, email=f'asha{self.counter}@example.com', email_verified=True)

    @staticmethod
    def client_for(user: User | None) -> APIClient:
        client = APIClient()
        if user:
            client.force_authenticate(user)
        return client

    def post(self, document_type: str, file: SimpleUploadedFile, user: User | None = None, **extra):
        data = {'document_type': document_type, 'file': file, **extra}
        return self.client_for(user or self.member).post(BASE + 'create/', data, format='multipart')

    def add(self, user: User, document_type: str = 'address_proof', data: bytes | None = None, name: str = 'proof.pdf') -> MemberDocument:
        return MemberDocument.add(user, document_type, upload(name, data or unique_pdf(f'{user.pk}-{document_type}-{MemberDocument.objects.count()}')))

    def stored_files(self) -> list[Path]:
        return [p for p in Path(self.root).rglob('*') if p.is_file()]

    def purge_disk(self) -> None:
        for path in self.stored_files():
            path.unlink()


class UploadTests(DocumentBase):
    def tearDown(self) -> None:
        self.purge_disk()

    def test_a_member_uploads_a_document(self) -> None:
        response = self.post('aadhaar', upload('Aadhaar front.pdf', PDF, 'application/pdf'), label='front side')
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data['data']
        self.assertTrue(response.data['status'])
        self.assertEqual(set(data), {'documentId', 'documentType', 'label', 'fileName', 'contentType', 'sizeBytes', 'createdDateTime', 'downloadUrl'})
        self.assertEqual((data['documentType'], data['label'], data['fileName'], data['contentType'], data['sizeBytes']),
                         ('aadhaar', 'front side', 'Aadhaar front.pdf', 'application/pdf', len(PDF)))
        self.assertEqual(data['downloadUrl'], f"{BASE}download/?document_id={data['documentId']}")
        document = MemberDocument.objects.get()
        self.assertEqual(document.user_id, self.member.user_id)

    def test_the_stored_name_is_the_hash_never_the_uploaded_name_and_lives_outside_media(self) -> None:
        self.post('other', upload('../../../etc/passwd.pdf', PDF, 'text/html'))
        document = MemberDocument.objects.get()
        stored = Path(document.file.name)
        self.assertEqual(stored.name, f'{document.sha256[:32]}.pdf')
        self.assertNotIn('passwd', document.file.name)
        self.assertEqual(str(stored.parent), str(self.member.user_id))
        [on_disk] = self.stored_files()
        self.assertTrue(str(on_disk).startswith(self.root))
        from django.conf import settings
        self.assertFalse(str(on_disk).startswith(str(settings.MEDIA_ROOT)))
        self.assertEqual(on_disk.read_bytes(), PDF)

    def test_the_client_content_type_and_extension_are_not_trusted(self) -> None:
        self.post('other', upload('notes.txt', PDF, 'image/png'))
        self.assertEqual(MemberDocument.objects.get().content_type, 'application/pdf')
        self.assertTrue(MemberDocument.objects.get().file.name.endswith('.pdf'))

    def test_any_harmless_file_type_is_accepted(self) -> None:
        samples = [('letter.docx', b'PK\x03\x04' + b'\x00' * 40), ('notes.txt', b'my address is 12 Main Road'), ('data.csv', b'a,b\n1,2\n'),
                   ('x.zip', b'PK\x03\x05' + b'\x00' * 30), ('blob.xyz', bytes(range(256))), ('photo.png', PNG), ('scan.jpg', JPG)]
        types = ['other', 'address_proof', 'pan', 'aadhaar', 'police_verification', 'character_certificate', 'father_verification']
        for index, (name, data) in enumerate(samples):
            cache.clear()
            response = self.post(types[index], upload(name, data + bytes([index])))
            self.assertEqual(response.status_code, 200, (name, response.data))
        self.assertEqual(MemberDocument.objects.count(), len(samples))

    def test_script_capable_and_executable_files_are_refused_and_nothing_is_stored(self) -> None:
        refused = [
            ('a.html', b'hello'), ('a.svg', b'hello'), ('a.js', b'hello'), ('a.exe', b'hello'), ('a.sh', b'hello'), ('a.bat', b'hello'), ('a.php', b'hello'),
            ('invoice.php.jpg', JPG), ('a.HTML', b'hello'), ('page.pdf', b'<html><script>alert(1)</script></html>'), ('logo.png', b'<svg onload=alert(1)>'),
            ('doc.pdf', b'MZ\x90\x00' + b'\x00' * 20), ('doc.pdf', b'\x7fELF' + b'\x00' * 20), ('run.txt', b'#!/bin/sh\nid'), ('x.txt', b'<?php system($_GET[1]);'),
        ]
        for name, data in refused:
            cache.clear()
            response = self.post('other', upload(name, data))
            self.assertEqual(response.status_code, 400, name)
            self.assertFalse(response.data['status'])
            self.assertIn('not allowed', str(response.data), name)
        self.assertEqual(MemberDocument.objects.count(), 0)
        self.assertEqual(self.stored_files(), [])

    def test_empty_oversized_and_malformed_requests(self) -> None:
        self.assertEqual(self.post('other', upload('a.pdf', b'')).status_code, 400)
        with mock.patch.object(Configurations, 'member_document_max_bytes', 100):
            self.assertEqual(self.post('other', upload('a.pdf', PDF + b'x' * 100)).status_code, 400)
            self.assertEqual(self.post('other', upload('a.pdf', PDF[:50])).status_code, 200)
        client = self.client_for(self.member)
        self.assertEqual(client.post(BASE + 'create/', {'document_type': 'other'}, format='multipart').status_code, 400)
        self.assertEqual(self.post('passport', upload('a.pdf', PDF)).status_code, 400)
        self.assertEqual(self.post('other', upload('b.pdf', unique_pdf('1')), label='x' * 101).status_code, 400)
        self.assertEqual(client.post(BASE + 'create/', {'document_type': 'other', 'file': 'not a file'}, format='multipart').status_code, 400)
        self.assertEqual(client.post(BASE + 'create/', {'document_type': 'other'}, format='json').status_code, 415)
        self.assertEqual(MemberDocument.objects.count(), 1)

    def test_the_size_limit_is_exact_at_both_layers(self) -> None:
        limit = len(PDF) + 10
        with mock.patch.object(Configurations, 'member_document_max_bytes', limit):
            self.assertEqual(self.post('other', upload('exact.pdf', PDF + b'x' * 10)).status_code, 200)     # exactly the limit is fine
            cache.clear()
            self.assertEqual(self.post('other', upload('over.pdf', PDF + b'y' * 11)).status_code, 400)      # one byte more is not
            with self.assertRaises(ValueError):                                                          # the model refuses it too
                MemberDocument.check_upload(self.member, 'pan', 'over.pdf', PDF + b'z' * 11)
            self.assertEqual(MemberDocument.check_upload(self.member, 'pan', 'ok.pdf', PDF + b'z' * 10)[0], 'pdf')

    def test_the_model_refuses_empty_content_by_itself(self) -> None:
        with self.assertRaises(ValueError):
            MemberDocument.check_upload(self.member, 'other', 'a.pdf', b'')

    def test_authentication_roles_and_methods(self) -> None:
        file = upload('a.pdf', PDF)
        self.assertEqual(self.client_for(None).post(BASE + 'create/', {'document_type': 'other', 'file': file}, format='multipart').status_code, 401)
        self.assertEqual(self.post('other', upload('a.pdf', PDF), user=self.admin).status_code, 403)
        for method in ('get', 'put', 'patch', 'delete'):
            self.assertEqual(getattr(self.client_for(self.member), method)(BASE + 'create/').status_code, 405, method)
        User.objects.filter(pk=self.member.pk).update(is_active=False)
        self.assertEqual(self.post('other', upload('a.pdf', PDF), user=User.objects.get(pk=self.member.pk)).status_code, 403)
        self.assertEqual(MemberDocument.objects.count(), 0)

    def test_the_owner_cannot_be_chosen_by_the_client(self) -> None:
        self.post('other', upload('a.pdf', PDF), user_id=self.other.user_id, user=self.member)
        self.client_for(self.member).post(BASE + 'create/?user_id=%d' % self.other.user_id, {'document_type': 'other', 'file': upload('b.pdf', unique_pdf('b'))}, format='multipart')
        self.assertEqual(set(MemberDocument.objects.values_list('user_id', flat=True)), {self.member.user_id})

    def test_limits_per_type_per_member_and_for_the_profile_photo(self) -> None:
        for index in range(3):
            cache.clear()
            self.assertEqual(self.post('address_proof', upload(f'p{index}.pdf', unique_pdf(str(index)))).status_code, 200)
        cache.clear()
        over = self.post('address_proof', upload('p9.pdf', unique_pdf('9')))
        self.assertEqual(over.status_code, 400)
        self.assertIn('limit for this document type', str(over.data))
        self.assertEqual(self.post('pan', upload('pan.pdf', unique_pdf('pan'))).status_code, 200)      # another type is still free
        self.assertEqual(self.post('address_proof', upload('p.pdf', unique_pdf('o')), user=self.other).status_code, 200)   # limits are per member
        with mock.patch.object(Configurations, 'member_document_max_per_member', 4):
            cache.clear()
            total = self.post('other', upload('t.pdf', unique_pdf('t')))
        self.assertEqual(total.status_code, 400)
        self.assertIn('limit of uploaded files', str(total.data))

    def test_profile_photo_is_one_image(self) -> None:
        self.assertEqual(self.post('profile_photo', upload('me.pdf', PDF)).status_code, 400)
        self.assertEqual(self.post('profile_photo', upload('me.txt', b'not an image')).status_code, 400)
        self.assertEqual(self.post('profile_photo', upload('me.png', PNG)).status_code, 200)
        second = self.post('profile_photo', upload('me2.jpg', JPG))
        self.assertEqual(second.status_code, 400)
        self.assertEqual(MemberDocument.objects.filter(document_type='profile_photo').count(), 1)

    def test_the_same_file_cannot_be_uploaded_twice_but_another_member_may(self) -> None:
        self.assertEqual(self.post('aadhaar', upload('a.pdf', PDF)).status_code, 200)
        again = self.post('pan', upload('renamed.pdf', PDF))
        self.assertEqual(again.status_code, 400)
        self.assertIn('already uploaded', str(again.data))
        self.assertEqual(self.post('aadhaar', upload('a.pdf', PDF), user=self.other).status_code, 200)
        self.assertEqual(len(self.stored_files()), 2)

    def test_upload_rate_limit_is_per_member(self) -> None:
        with mock.patch.dict(DocumentUploadThrottle.THROTTLE_RATES, {'member_document_upload': '2/hour'}):
            statuses = [self.post('other', upload(f'f{i}.pdf', unique_pdf(f'r{i}'))).status_code for i in range(4)]
            self.assertEqual(statuses, [200, 200, 429, 429])
            self.assertEqual(self.post('other', upload('o.pdf', unique_pdf('o')), user=self.other).status_code, 200)

    def test_a_failed_save_leaves_no_file_behind(self) -> None:
        with mock.patch.object(MemberDocument, 'save', side_effect=RuntimeError('db down')), self.assertRaises(RuntimeError):
            MemberDocument.add(self.member, 'other', upload('a.pdf', PDF))
        self.assertEqual(self.stored_files(), [])
        self.assertEqual(MemberDocument.objects.count(), 0)


class ReadDeleteTests(DocumentBase):
    def tearDown(self) -> None:
        self.purge_disk()

    def setUp(self) -> None:
        super().setUp()
        self.mine = self.add(self.member, 'aadhaar', PDF, 'Aadhaar scan.pdf')
        self.theirs = self.add(self.other, 'pan', unique_pdf('theirs'), 'their pan.pdf')

    def get(self, path: str, user: User | None, **params):
        return self.client_for(user).get(BASE + path, params)

    def test_get_returns_only_my_own_and_404_for_others(self) -> None:
        ok = self.get('get/', self.member, document_id=self.mine.document_id)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.data['data']['documentId'], self.mine.document_id)
        theirs = self.get('get/', self.member, document_id=self.theirs.document_id)
        missing = self.get('get/', self.member, document_id=999999)
        self.assertEqual((theirs.status_code, missing.status_code), (404, 404))
        self.assertEqual(theirs.data, missing.data)                       # an existing id looks exactly like a missing one
        self.assertEqual(self.get('get/', self.member, document_id=0).status_code, 400)
        self.assertEqual(self.get('get/', self.member).status_code, 400)

    def test_authentication_and_roles_on_every_read_endpoint(self) -> None:
        for path in ('get/', 'get_all/', 'download/'):
            self.assertEqual(self.get(path, None, document_id=self.mine.document_id).status_code, 401, path)
            self.assertEqual(self.get(path, self.admin, document_id=self.mine.document_id).status_code, 403, path)
        self.assertEqual(self.client_for(None).delete(BASE + 'delete/?document_id=%d' % self.mine.document_id).status_code, 401)
        self.assertEqual(self.client_for(self.admin).delete(BASE + 'delete/?document_id=%d' % self.mine.document_id).status_code, 403)
        self.assertTrue(MemberDocument.objects.filter(pk=self.mine.pk).exists())

    def test_get_all_lists_only_my_documents_with_filters_sort_search_and_paging(self) -> None:
        self.add(self.member, 'pan', unique_pdf('pan'), 'pan card.pdf')
        self.add(self.member, 'pan', unique_pdf('pan2'), 'second.pdf')
        MemberDocument.objects.filter(download_name='second.pdf').update(label='spare copy')
        everything = self.get('get_all/', self.member, limit=100)
        self.assertEqual(everything.status_code, 200)
        names = [row['fileName'] for row in everything.data['data']['data']]
        self.assertCountEqual(names, ['Aadhaar scan.pdf', 'pan card.pdf', 'second.pdf'])
        self.assertNotIn('their pan.pdf', str(everything.data))
        only_pan = self.get('get_all/', self.member, filter_key='documentType', filter_value='pan')
        self.assertEqual(len(only_pan.data['data']['data']), 2)
        self.assertEqual([r['label'] for r in self.get('get_all/', self.member, search_key='spare').data['data']['data']], ['spare copy'])
        by_type = self.get('get_all/', self.member, sort_by='documentType', sort_order='asc')
        self.assertEqual([r['documentType'] for r in by_type.data['data']['data']], ['aadhaar', 'pan', 'pan'])
        page = self.get('get_all/', self.member, limit=2)
        self.assertEqual((page.data['data']['totalPage'], len(page.data['data']['data'])), (2, 2))
        self.assertIn('nextPageUrl', page.data['data'])
        subset = self.get('get_all/', self.member, values='documentId,fileName')
        self.assertEqual(set(subset.data['data']['data'][0]), {'documentId', 'fileName'})
        for bad in ({'filter_key': 'sha256', 'filter_value': 'x'}, {'sort_by': 'file'}, {'values': 'sha256'}, {'filter_key': 'userId', 'filter_value': '1'}):
            self.assertEqual(self.get('get_all/', self.member, **bad).status_code, 400, bad)

    def test_nothing_internal_is_ever_returned(self) -> None:
        text = str(self.get('get_all/', self.member).data) + str(self.get('get/', self.member, document_id=self.mine.document_id).data)
        for secret in (self.mine.sha256, self.mine.file.name, self.root, 'sha256', 'file_name', str(self.other.membership_id), self.other.email, 'private_media'):
            self.assertNotIn(secret, text, secret)

    def test_delete_removes_the_row_and_the_file(self) -> None:
        path = Path(self.root) / self.mine.file.name
        self.assertTrue(path.is_file())
        response = self.client_for(self.member).delete(BASE + 'delete/?document_id=%d' % self.mine.document_id)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(MemberDocument.objects.filter(pk=self.mine.pk).exists())
        self.assertFalse(path.exists())
        self.assertEqual(self.client_for(self.member).delete(BASE + 'delete/?document_id=%d' % self.mine.document_id).status_code, 404)

    def test_i_cannot_delete_someone_elses_document(self) -> None:
        path = Path(self.root) / self.theirs.file.name
        response = self.client_for(self.member).delete(BASE + 'delete/?document_id=%d' % self.theirs.document_id)
        self.assertEqual(response.status_code, 404)
        self.assertTrue(MemberDocument.objects.filter(pk=self.theirs.pk).exists())
        self.assertTrue(path.is_file())

    def test_removing_a_member_removes_their_files(self) -> None:
        path = Path(self.root) / self.theirs.file.name
        self.other.delete()
        self.assertTrue(not path.exists() and not MemberDocument.objects.filter(pk=self.theirs.pk).exists())
        self.assertTrue((Path(self.root) / self.mine.file.name).is_file())

    def test_a_freed_slot_can_be_used_again(self) -> None:
        for index in range(3):
            self.add(self.member, 'other', unique_pdf(f'slot{index}'))
        self.assertEqual(self.post('other', upload('x.pdf', unique_pdf('x'))).status_code, 400)
        victim = MemberDocument.objects.filter(user=self.member, document_type='other').first()
        self.client_for(self.member).delete(BASE + 'delete/?document_id=%d' % victim.document_id)
        self.assertEqual(self.post('other', upload('x.pdf', unique_pdf('x'))).status_code, 200)

    def post(self, document_type: str, file: SimpleUploadedFile, user: User | None = None, **extra):   # noqa: D401
        cache.clear()
        return super().post(document_type, file, user, **extra)


class DownloadTests(DocumentBase):
    def tearDown(self) -> None:
        self.purge_disk()

    def test_the_owner_downloads_the_exact_bytes_as_a_safe_attachment(self) -> None:
        document = self.add(self.member, 'aadhaar', PDF, 'Aadhaar front.pdf')
        response = self.client_for(self.member).get(BASE + 'download/', {'document_id': document.document_id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), PDF)
        self.assertEqual(response['Content-Type'], 'application/octet-stream')
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertIn('Aadhaar front.pdf', response['Content-Disposition'])
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertIn('sandbox', response['Content-Security-Policy'])
        self.assertIn('no-store', response['Cache-Control'])

    def test_a_download_of_someone_elses_or_a_missing_document_is_404(self) -> None:
        theirs = self.add(self.other, 'pan', PDF, 'pan.pdf')
        client = self.client_for(self.member)
        first = client.get(BASE + 'download/', {'document_id': theirs.document_id})
        second = client.get(BASE + 'download/', {'document_id': 424242})
        self.assertEqual((first.status_code, second.status_code), (404, 404))
        self.assertEqual(first.data, second.data)
        self.assertNotIn(b'%PDF', first.content)

    def test_files_are_not_reachable_through_the_public_media_url(self) -> None:
        document = self.add(self.member, 'aadhaar', PDF, 'a.pdf')
        with override_settings(DEBUG=True):
            for path in (f'/media/{document.file.name}', f'/media/member_documents/{document.file.name}', f'/media/private_media/{document.file.name}'):
                self.assertEqual(Client().get(path).status_code, 404, path)
        with self.assertRaises(ValueError):
            PrivateStorage().url(document.file.name)

    def test_the_download_never_serves_html_inline_even_if_the_content_looks_like_it(self) -> None:
        document = self.add(self.member, 'other', PDF + b'\n<html><script>alert(1)</script></html>', 'x.pdf')
        response = self.client_for(self.member).get(BASE + 'download/', {'document_id': document.document_id})
        self.assertEqual(response['Content-Type'], 'application/octet-stream')
        self.assertTrue(response['Content-Disposition'].startswith('attachment'))


# ======================================================================== admin

@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class AdminTests(DocumentBase):
    LIST = '/admin/member_documents/memberdocument/'
    LOGS = '/admin/member_documents/memberdocumentaccesslog/'

    def setUp(self) -> None:
        super().setUp()
        call_command('setup_admin_groups', stdout=StringIO())
        self.document = self.add(self.member, 'aadhaar', PDF, 'Aadhaar front.pdf')
        self.reviewer = self.staff('Document Reviewers')

    def tearDown(self) -> None:
        self.purge_disk()

    def staff(self, *groups: str, perms: tuple[str, ...] = ()) -> User:
        self.counter += 1
        user = User.objects.create_user(full_name='Staff', password=PASSWORD, email=f'staff{self.counter}@example.com', is_staff=True, role='admin', email_verified=True)
        user.groups.add(*Group.objects.filter(name__in=groups))
        from django.contrib.auth.models import Permission
        for code in perms:
            user.user_permissions.add(Permission.objects.get(codename=code))
        return user

    @staticmethod
    def web(user: User | None) -> Client:
        client = Client()
        if user:
            client.force_login(user)
        return client

    def download_url(self) -> str:
        return f'{self.LIST}{self.document.pk}/download/'

    def test_a_reviewer_lists_searches_and_downloads(self) -> None:
        page = self.web(self.reviewer).get(self.LIST)
        self.assertContains(page, self.member.membership_id)
        self.assertContains(page, 'Aadhaar front.pdf')
        self.assertContains(self.web(self.reviewer).get(self.LIST + f'?q={self.member.membership_id}'), 'Aadhaar front.pdf')
        self.assertNotContains(self.web(self.reviewer).get(self.LIST + '?q=NOSUCHMEMBER'), 'Aadhaar front.pdf')
        response = self.web(self.reviewer).get(self.download_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), PDF)
        self.assertEqual(response['Content-Type'], 'application/octet-stream')
        self.assertTrue(response['Content-Disposition'].startswith('attachment'))
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')

    def test_every_admin_download_is_logged(self) -> None:
        self.assertEqual(MemberDocumentAccessLog.objects.count(), 0)
        b''.join(self.web(self.reviewer).get(self.download_url()).streaming_content)
        b''.join(self.web(self.reviewer).get(self.download_url()).streaming_content)
        logs = list(MemberDocumentAccessLog.objects.order_by('log_id'))
        self.assertEqual(len(logs), 2)
        self.assertEqual((logs[0].admin_id, logs[0].member_id, logs[0].document_id, logs[0].document_type),
                         (self.reviewer.user_id, self.member.user_id, self.document.pk, 'aadhaar'))

    def test_a_member_downloading_their_own_file_is_not_an_admin_read(self) -> None:
        self.client_for(self.member).get(BASE + 'download/', {'document_id': self.document.document_id})
        self.assertEqual(MemberDocumentAccessLog.objects.count(), 0)

    def test_people_without_the_permission_are_refused_and_nothing_is_logged(self) -> None:
        viewer = self.staff(perms=('view_memberdocument',))
        for user in (self.staff(), self.staff('Support Handlers'), self.staff('Content Publishers'), self.staff('Knowledge Approvers'), viewer):
            self.assertEqual(self.web(user).get(self.download_url()).status_code, 403)
        self.assertEqual(self.web(viewer).get(self.LIST).status_code, 200)         # may look, not download
        self.assertEqual(self.web(self.staff('Support Handlers')).get(self.LIST).status_code, 403)
        self.assertEqual(self.web(None).get(self.download_url()).status_code, 302)
        self.assertEqual(self.web(self.member).get(self.download_url()).status_code, 302)   # a member session is not a staff session
        self.assertEqual(MemberDocumentAccessLog.objects.count(), 0)

    def test_missing_files_and_ids_are_404_and_not_logged(self) -> None:
        Path(self.root, self.document.file.name).unlink()
        self.assertEqual(self.web(self.reviewer).get(self.download_url()).status_code, 404)
        self.assertEqual(self.web(self.reviewer).get(f'{self.LIST}999999/download/').status_code, 404)
        self.assertEqual(MemberDocumentAccessLog.objects.count(), 0)

    def test_the_admin_cannot_add_change_or_delete_documents(self) -> None:
        client = self.web(self.reviewer)
        self.assertEqual(client.get(self.LIST + 'add/').status_code, 403)
        client.post(f'{self.LIST}{self.document.pk}/change/', {'label': 'tampered'})
        client.post(f'{self.LIST}{self.document.pk}/delete/', {'post': 'yes'})
        client.post(self.LIST, {'action': 'delete_selected', '_selected_action': [self.document.pk], 'post': 'yes'})
        self.document.refresh_from_db()
        self.assertEqual(self.document.label, '')
        self.assertTrue(Path(self.root, self.document.file.name).is_file())

    def test_the_access_log_is_for_superusers_only_and_read_only(self) -> None:
        b''.join(self.web(self.reviewer).get(self.download_url()).streaming_content)
        self.assertEqual(self.web(self.reviewer).get(self.LOGS).status_code, 403)
        root = User.objects.create_superuser(full_name='Root', password=PASSWORD, email='root@example.com')
        self.assertContains(self.web(root).get(self.LOGS), self.reviewer.membership_id)
        self.assertEqual(self.web(root).get(self.LOGS + 'add/').status_code, 403)
        log = MemberDocumentAccessLog.objects.get()
        self.web(root).post(f'{self.LOGS}{log.pk}/delete/', {'post': 'yes'})
        self.assertTrue(MemberDocumentAccessLog.objects.filter(pk=log.pk).exists())

    def test_log_rows_outlive_the_file_and_the_admin(self) -> None:
        b''.join(self.web(self.reviewer).get(self.download_url()).streaming_content)
        document_id = self.document.pk
        self.document.delete()
        self.reviewer.delete()
        log = MemberDocumentAccessLog.objects.get()
        self.assertEqual((log.document_id, log.admin_id), (document_id, None))

    def test_group_setup_gives_exactly_view_and_download(self) -> None:
        codes = set(Group.objects.get(name='Document Reviewers').permissions.values_list('codename', flat=True))
        self.assertEqual(codes, {'view_memberdocument', 'download_memberdocument'})


class DeclarationTests(TestCase):
    def test_model_and_storage_declarations(self) -> None:
        field = MemberDocument._meta.get_field('file')
        self.assertIsInstance(field.storage, (PrivateStorage, FileSystemStorage))
        self.assertTrue(any(c.name == 'unique_member_document_content' for c in MemberDocument._meta.constraints))
        self.assertEqual(MemberDocument._meta.db_table, 'member_document')
        self.assertIn('download_memberdocument', [p[0] for p in MemberDocument._meta.permissions])
        self.assertTrue(PrivateStorage().base_location.endswith('private_media') or PrivateStorage().base_location)

    def test_the_private_folder_is_not_inside_media_root(self) -> None:
        from django.conf import settings
        self.assertNotIn(str(settings.MEDIA_ROOT), str(settings.PRIVATE_MEDIA_ROOT))

    def test_schema_documents_the_endpoints(self) -> None:
        body = APIClient().get('/api/schema/').content.decode()
        for path in ('create', 'get', 'get_all', 'delete', 'download'):
            self.assertIn(f'/member_documents/document/{path}/', body)
        self.assertIn('multipart/form-data', body)
