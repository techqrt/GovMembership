from django.core.exceptions import ValidationError
from django.test import Client

from gmp_apps.portals.models import ComplaintPortal
from gmp_apps.portals.tests import PortalApiBase

COMPLAINT = 'https://pgportal.gov.in/Registration'
TRACK = 'https://pgportal.gov.in/Status'
LIST = '/admin/portals/complaintportal/'


class MemberViewTests(PortalApiBase):
    def rows(self, user) -> list[dict]:
        return self.as_user(user).get('/portals/get_all/?limit=100').data['data']['data']

    def test_links_default_to_null_and_visit_portal_stays(self) -> None:
        self.portal('Plain', 'https://plain.gov.in')
        row = self.rows(self.member())[0]
        self.assertEqual((row['fileComplaintUrl'], row['trackStatusUrl'], row['officialUrl']), (None, None, 'https://plain.gov.in'))

    def test_links_are_returned_when_given(self) -> None:
        self.portal('Full', 'https://full.gov.in', file_complaint_url=COMPLAINT, track_status_url=TRACK)
        self.portal('Only one', 'https://one.gov.in', track_status_url=TRACK)
        rows = {r['name']: r for r in self.rows(self.member())}
        self.assertEqual((rows['Full']['fileComplaintUrl'], rows['Full']['trackStatusUrl']), (COMPLAINT, TRACK))
        self.assertEqual((rows['Only one']['fileComplaintUrl'], rows['Only one']['trackStatusUrl']), (None, TRACK))

    def test_hidden_portals_do_not_leak_their_links(self) -> None:
        self.portal('Off', 'https://off.gov.in', file_complaint_url='https://secret-off.gov.in/file', is_active=False)
        self.assertNotIn('secret-off', str(self.rows(self.member())))

    def test_the_dashboard_carries_them_too(self) -> None:
        self.portal('Dash', 'https://dash.gov.in', file_complaint_url=COMPLAINT, track_status_url=TRACK)
        sections = {s['key']: s for s in self.as_user(self.member()).get('/dashboard/get/').data['data']['sections']}
        item = sections['portals']['data']['items'][0]
        self.assertEqual((item['fileComplaintUrl'], item['trackStatusUrl']), (COMPLAINT, TRACK))

    def test_the_detail_endpoint_has_them_too(self) -> None:
        portal = self.portal('Detail', 'https://detail.gov.in', file_complaint_url=COMPLAINT, track_status_url=TRACK)
        data = self.as_user(self.member()).get(f'/portals/get/?portal_id={portal.portal_id}').data['data']
        self.assertEqual((data['fileComplaintUrl'], data['trackStatusUrl']), (COMPLAINT, TRACK))

    def test_authentication_still_required(self) -> None:
        self.assertEqual(self.as_user(None).get('/portals/get_all/').status_code, 401)

    def test_the_schema_lists_the_new_fields(self) -> None:
        body = self.as_user(None).get('/api/schema/').content.decode()
        self.assertIn('fileComplaintUrl', body)
        self.assertIn('trackStatusUrl', body)


class SafetyTests(PortalApiBase):
    BAD = ('javascript:alert(1)', 'https://user:pw@a.gov.in/', 'https://10.0.0.1/', 'ftp://a.gov.in/', 'http://intranet', 'data:text/html,x',
           'https://a.gov.in/has space', 'vbscript:x', '//evil.example/x')

    def test_unsafe_links_are_refused_on_every_save_path(self) -> None:
        for field in ('file_complaint_url', 'track_status_url'):
            for bad in self.BAD:
                with self.assertRaises(ValidationError, msg=(field, bad)):
                    ComplaintPortal.objects.create(name='Bad', category=self.general, official_url='https://ok.gov.in', **{field: bad})
        self.assertEqual(ComplaintPortal.objects.count(), 0)

    def test_blank_and_valid_links_are_accepted_and_trimmed(self) -> None:
        portal = ComplaintPortal.objects.create(
            name='Trim', category=self.general, official_url='https://trim.gov.in', file_complaint_url='  ' + COMPLAINT + ' ', track_status_url='   ',
        )
        self.assertEqual((portal.file_complaint_url, portal.track_status_url), (COMPLAINT, ''))

    def test_the_links_can_be_on_any_official_host_and_shared_between_portals(self) -> None:
        for index in range(2):
            self.portal(f'Shared {index}', f'https://shared{index}.gov.in', file_complaint_url='https://common.gov.in/file')
        self.assertEqual(ComplaintPortal.objects.count(), 2)        # only the official URL is unique

    def test_the_official_url_is_still_required_and_unique(self) -> None:
        self.portal('First', 'https://first.gov.in')
        with self.assertRaises(Exception):
            ComplaintPortal.objects.create(name='Dup', category=self.general, official_url='https://first.gov.in/', file_complaint_url=COMPLAINT)
        with self.assertRaises(ValidationError):
            ComplaintPortal.objects.create(name='Empty', category=self.general, official_url='', file_complaint_url=COMPLAINT)


class AdminTests(PortalApiBase):
    def setUp(self) -> None:
        super().setUp()
        self.web = Client()
        self.web.force_login(self.staff('Portal Managers'))

    def form(self, **overrides) -> dict:
        data = {'name': 'CPGRAMS', 'category': self.general.pk, 'department': 'DARPG', 'description': 'Central grievances',
                'official_url': 'https://pgportal.gov.in/', 'file_complaint_url': COMPLAINT, 'track_status_url': TRACK,
                'sort_order': '0', 'is_active': 'on', '_save': 'Save'}
        data.update(overrides)
        return {k: v for k, v in data.items() if v != ''}

    def test_add_edit_and_clear_the_links(self) -> None:
        self.web.post(LIST + 'add/', self.form(), follow=True)
        portal = ComplaintPortal.objects.get()
        self.assertEqual((portal.file_complaint_url, portal.track_status_url), (COMPLAINT, TRACK))
        blank = {**self.form(), 'track_status_url': ''}     # posted empty (an omitted field would be left alone)
        self.web.post(f'{LIST}{portal.pk}/change/', blank, follow=True)
        portal.refresh_from_db()
        self.assertEqual((portal.file_complaint_url, portal.track_status_url), (COMPLAINT, ''))

    def test_unsafe_links_are_rejected_with_nothing_saved(self) -> None:
        for field in ('file_complaint_url', 'track_status_url'):
            for bad in ('javascript:alert(1)', 'https://user:pw@a.gov.in/', 'https://10.0.0.1/', 'ftp://a.gov.in/'):
                response = self.web.post(LIST + 'add/', self.form(**{field: bad}))
                self.assertEqual(response.status_code, 200, (field, bad))   # the form is shown again with an error
        self.assertEqual(ComplaintPortal.objects.count(), 0)

    def test_the_form_offers_both_fields_and_search_finds_them(self) -> None:
        page = self.web.get(LIST + 'add/')
        self.assertContains(page, 'name="file_complaint_url"')
        self.assertContains(page, 'name="track_status_url"')
        self.portal('Findable', 'https://findable.gov.in', file_complaint_url='https://zzmarker.gov.in/file')
        self.assertContains(self.web.get(LIST + '?q=zzmarker'), 'Findable')

    def test_other_staff_cannot_edit_portals(self) -> None:
        other = Client()
        other.force_login(self.staff('Support Handlers'))
        self.assertEqual(other.get(LIST + 'add/').status_code, 403)
        self.assertEqual(other.post(LIST + 'add/', self.form()).status_code, 403)
        self.assertEqual(ComplaintPortal.objects.count(), 0)
