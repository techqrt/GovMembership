"""FG8 break-it tests: five ways real people can break the national / state schemes feature, one test class each.

1. A member's own spelling of a state (profile text, abbreviations of the source, stray spaces and capitals).
2. Paging, searching and sorting a filtered list across many schemes.
3. The whole life of a scheme: imported, reviewed, published, moved between levels, hidden, re-synced.
4. An admin correcting a wrong guess, which nothing automatic may ever undo.
5. Hostile and garbage input: unknown keys, injection text, look-alike letters, huge values, bad paging, wrong roles.
"""
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import Client

from gmp.config import Configurations
from gmp_apps.schemes import tests as base
from gmp_apps.schemes.classification import STATES
from gmp_apps.schemes.models import Scheme
from gmp_apps.schemes.sync.runner import SchemeSyncRunner

LIST = '/schemes/get_all/'
OPTIONS = '/schemes/state/get_all/'
ADMIN_LIST = '/admin/schemes/scheme/'


def rows(response) -> list[dict]:
    assert response.status_code == 200, (response.status_code, getattr(response, 'data', response.content))
    return response.data['data']['data']


class BreakItBase(base.SchemeApiBase):
    def setUp(self) -> None:
        super().setUp()
        self.member_client = self.as_user(self.member())
        self.reviewer = self.staff('Scheme Reviewers')
        self.admin = Client()
        self.admin.force_login(self.reviewer)
        for name, value in (('scheme_sync_delay_seconds', 0.0), ('scheme_sync_max_consecutive_errors', 3)):
            patcher = mock.patch.object(Configurations, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def filtered(self, key: str, value: str, **extra) -> list[dict]:
        return rows(self.member_client.get(LIST, {'filter_key': key, 'filter_value': value, **extra}))

    def titles(self, key: str, value: str, **extra) -> list[str]:
        return sorted(r['title'] for r in self.filtered(key, value, **extra))

    def sync(self, pages: dict[str, tuple[str, str]]) -> None:
        source = base.FakeSource(
            base.sitemap(*[(base.url(slug), lastmod) for slug, (lastmod, _) in pages.items()]),
            {base.url(slug): html for slug, (_, html) in pages.items()},
        )
        SchemeSyncRunner(source=source, sleep=lambda seconds: None).run()

    def admin_post(self, scheme: Scheme, **overrides):
        return self.admin.post(f'{ADMIN_LIST}{scheme.pk}/change/', base.SchemeAdminRichTests.form(self, scheme, **overrides), follow=True)  # type: ignore[arg-type]

    def admin_action(self, action: str, *schemes: Scheme):
        return self.admin.post(ADMIN_LIST, {'action': action, '_selected_action': [s.pk for s in schemes]}, follow=True)


class BreakItSpellingTests(BreakItBase):
    """1. The member's profile state is free text, and the source writes names its own way. Whatever reasonable
    spelling reaches the filter must find the state's schemes, not an error that breaks the screen."""

    def test_every_reasonable_spelling_finds_the_same_schemes(self) -> None:
        self.scheme('Odisha one', level='state', state='Odisha')
        self.scheme('J and K one', level='state', state='Jammu and Kashmir')
        self.scheme('Delhi one', level='state', state='Delhi')
        self.scheme('Up one', level='state', state='Uttar Pradesh')
        spellings = {
            'Odisha': ['Odisha', 'odisha', 'ODISHA', '  Odisha  ', 'Orissa', 'orissa'],
            'Jammu and Kashmir': ['Jammu and Kashmir', 'jammu and kashmir', 'Jammu & Kashmir', 'J&K'],
            'Delhi': ['Delhi', 'New Delhi', 'NCT of Delhi'],
            'Uttar Pradesh': ['Uttar Pradesh', 'uttar pradesh', 'UTTAR   PRADESH'],
        }
        for state, variants in spellings.items():
            expected = [s.title for s in Scheme.objects.filter(state=state)]
            for variant in variants:
                response = self.member_client.get(LIST, {'filter_key': 'state', 'filter_value': variant})
                self.assertEqual(response.status_code, 200, (variant, response.data))
                self.assertEqual([r['title'] for r in rows(response)], expected, variant)

    def test_a_name_the_app_got_from_the_options_list_always_works(self) -> None:
        for name in STATES[:6]:
            self.scheme(f'{name} one', level='state', state=name)
        for row in self.member_client.get(OPTIONS).data['data']['data']:
            self.assertEqual(len(self.filtered('state', row['state'])), row['count'], row['state'])

    def test_a_real_but_wrong_place_is_empty_not_an_error(self) -> None:
        self.scheme('Haryana one', level='state', state='Haryana')
        self.assertEqual(self.filtered('state', 'Kerala'), [])   # a valid state with no schemes


class BreakItPagingTests(BreakItBase):
    """2. A big filtered list, paged, searched and sorted: no scheme twice, none missing, none from another place."""

    def setUp(self) -> None:
        super().setUp()
        for i in range(7):
            self.scheme(f'Haryana pension {i}', level='state', state='Haryana', description=f'pension for group {i}')
        for i in range(3):
            self.scheme(f'Punjab pension {i}', level='state', state='Punjab', description='pension')
        for i in range(2):
            self.scheme(f'National pension {i}', level='national', description='pension')
        self.scheme('Haryana loan', level='state', state='Haryana', description='a loan')

    def walk(self, **extra) -> list[str]:
        seen: list[str] = []
        page_num = 1
        while True:
            response = self.member_client.get(LIST, {'filter_key': 'state', 'filter_value': 'Haryana', 'limit': 3, 'page_num': page_num, **extra})
            data = response.data['data']
            self.assertEqual(response.status_code, 200)
            seen += [r['title'] for r in data['data']]
            for row in data['data']:
                self.assertEqual((row['level'], row['state']), ('state', 'Haryana'))
            if page_num >= data['totalPage']:
                return seen
            page_num += 1

    def test_pages_cover_the_filtered_schemes_exactly_once(self) -> None:
        seen = self.walk(sort_by='title', sort_order='asc')
        self.assertEqual(len(seen), 8)
        self.assertEqual(len(set(seen)), 8)
        self.assertEqual(seen, sorted(seen))

    def test_search_inside_a_filter_only_narrows_it(self) -> None:
        seen = self.walk(search_key='pension')
        self.assertEqual(len(seen), 7)
        self.assertNotIn('Haryana loan', seen)
        self.assertEqual(self.titles('level', 'national', search_key='pension'), ['National pension 0', 'National pension 1'])

    def test_the_total_follows_the_filter_not_the_whole_list(self) -> None:
        response = self.member_client.get(LIST, {'filter_key': 'state', 'filter_value': 'Punjab', 'limit': 2})
        self.assertEqual(response.data['data']['totalPage'], 2)
        self.assertEqual(len(rows(self.member_client.get(LIST, {'filter_key': 'state', 'filter_value': 'Punjab', 'limit': 2, 'page_num': 2}))), 1)

    def test_a_page_past_the_end_is_a_clear_refusal(self) -> None:
        response = self.member_client.get(LIST, {'filter_key': 'state', 'filter_value': 'Punjab', 'limit': 2, 'page_num': 3})
        self.assertEqual(response.status_code, 400)


class BreakItLifecycleTests(BreakItBase):
    """3. The whole flow in one run: import, review, publish, filter, move between levels, hide, import again."""

    def pages(self, **department) -> dict[str, tuple[str, str]]:
        def one(slug: str, title: str, dept: str, lastmod: str = '2024-05-01') -> tuple[str, tuple[str, str]]:
            return slug, (lastmod, base.page(title, table=(('Department', department.get(slug, dept)),)))
        return dict([
            one('haryana-pension', 'Haryana Pension', 'Haryana Social Welfare'),
            one('central-loan', 'Central Loan', 'Ministry of Finance'),
            one('vague-grant', 'Vague Grant', 'Department of Agriculture'),
            one('punjab-aid', 'Punjab Aid', 'Punjab Welfare Department'),
        ])

    def by_title(self, title: str) -> Scheme:
        return Scheme.objects.get(title=title)

    def member_sections(self) -> dict:
        return {s['key']: s for s in self.member_client.get('/dashboard/get/').data['data']['sections']}

    def test_the_full_flow(self) -> None:
        # imported: pending, classified by the rules, invisible to members
        self.sync(self.pages())
        self.assertEqual(Scheme.objects.count(), 4)
        self.assertEqual(
            {s.title: (s.status, s.level, s.state) for s in Scheme.objects.all()},
            {'Haryana Pension': ('pending_review', 'state', 'Haryana'), 'Central Loan': ('pending_review', 'national', ''),
             'Vague Grant': ('pending_review', '', ''), 'Punjab Aid': ('pending_review', 'state', 'Punjab')},
        )
        self.assertEqual(rows(self.member_client.get(LIST)), [])
        self.assertEqual(self.member_client.get(OPTIONS).data['data']['data'], [])
        self.assertEqual(self.titles('level', 'state'), [])

        # an admin reviews and publishes all four
        self.admin_action('publish_selected', *Scheme.objects.all())
        self.assertEqual(Scheme.objects.filter(status='published').count(), 4)
        self.assertEqual(len(rows(self.member_client.get(LIST))), 4)
        self.assertEqual(self.titles('level', 'national'), ['Central Loan'])
        self.assertEqual(self.titles('level', 'state'), ['Haryana Pension', 'Punjab Aid'])
        self.assertEqual(self.titles('state', 'Haryana'), ['Haryana Pension'])
        self.assertEqual(
            self.member_client.get(OPTIONS).data['data']['data'],
            [{'level': 'national', 'state': None, 'count': 1}, {'level': 'state', 'state': 'Haryana', 'count': 1},
             {'level': 'state', 'state': 'Punjab', 'count': 1}],
        )

        # the scheme the rules could not place is listed but in neither filter, and the admin can find it
        self.assertIn('Vague Grant', [r['title'] for r in rows(self.member_client.get(LIST))])
        self.assertNotIn('Vague Grant', self.titles('level', 'national') + self.titles('level', 'state'))
        needs = self.admin.get(f'{ADMIN_LIST}?needs_level=missing').context['cl'].result_list
        self.assertEqual([s.title for s in needs], ['Vague Grant'])

        # the admin places it as national
        self.admin_post(self.by_title('Vague Grant'), level='national', state='')
        self.assertEqual(self.titles('level', 'national'), ['Central Loan', 'Vague Grant'])

        # and moves Haryana Pension from state to national in one save
        self.admin_post(self.by_title('Haryana Pension'), level='national', state='')
        self.assertEqual(self.titles('state', 'Haryana'), [])
        self.assertEqual(self.titles('level', 'national'), ['Central Loan', 'Haryana Pension', 'Vague Grant'])
        self.assertEqual(self.titles('level', 'state'), ['Punjab Aid'])
        self.assertEqual(self.member_client.get(OPTIONS).data['data']['data'][0], {'level': 'national', 'state': None, 'count': 3})

        # an unpublished scheme leaves the list, the filters and the counts straight away
        self.admin_action('unpublish_selected', self.by_title('Punjab Aid'))
        self.assertEqual(self.titles('level', 'state'), [])
        self.assertEqual([r['level'] for r in self.member_client.get(OPTIONS).data['data']['data']], ['national'])

        # the dashboard agrees with the list
        schemes = self.member_sections()['schemes']['data']
        self.assertEqual(schemes['total'], 3)
        self.assertEqual({i['title']: i['level'] for i in schemes['items']}, {'Central Loan': 'national', 'Haryana Pension': 'national', 'Vague Grant': 'national'})

        # the source changes (new content, even a different department): nothing the admin decided moves
        self.sync(self.pages(**{'haryana-pension': 'Punjab Welfare Department'}) | {'central-loan': ('2024-09-01', base.page('Central Loan', benefits=('Rs. 1',), table=(('Department', 'Haryana Finance'),)))})
        self.assertEqual(self.by_title('Haryana Pension').level, 'national')
        self.assertEqual((self.by_title('Central Loan').level, self.by_title('Central Loan').state), ('national', ''))
        self.assertEqual(self.by_title('Punjab Aid').status, 'unpublished')   # a re-import never re-publishes either

    def test_a_scheme_without_a_level_is_never_lost_from_the_full_list(self) -> None:
        self.sync(self.pages())
        self.admin_action('publish_selected', *Scheme.objects.all())
        everything = {r['title'] for r in rows(self.member_client.get(LIST))}
        in_a_filter = set(self.titles('level', 'national')) | set(self.titles('level', 'state'))
        self.assertEqual(everything - in_a_filter, {'Vague Grant'})


class BreakItCorrectionTests(BreakItBase):
    """4. The rules will sometimes be wrong (a public bank named after a state is a national scheme). Once an admin
    corrects it, nothing automatic may put the wrong answer back: not the sync, not the command, not the action."""

    def setUp(self) -> None:
        super().setUp()
        self.sync({'bank-loan': ('2024-05-01', base.page('Bank Loan', table=(('Department', 'Bank of Maharashtra'),)))})
        self.scheme_ = Scheme.objects.get()
        self.admin_action('publish_selected', self.scheme_)

    def test_the_rules_do_get_this_one_wrong_which_is_why_correction_matters(self) -> None:
        self.assertEqual((self.scheme_.level, self.scheme_.state), ('state', 'Maharashtra'))
        self.assertEqual(self.titles('state', 'Maharashtra'), ['Bank Loan'])

    def test_a_correction_is_not_undone_by_anything_automatic(self) -> None:
        self.admin_post(self.scheme_, level='national', state='')
        self.scheme_.refresh_from_db()
        self.assertEqual((self.scheme_.level, self.scheme_.state), ('national', ''))
        self.assertEqual(self.titles('state', 'Maharashtra'), [])

        # the source changes its page
        self.sync({'bank-loan': ('2024-09-01', base.page('Bank Loan v2', benefits=('Rs. 2',), table=(('Department', 'Bank of Maharashtra'),)))})
        # the bulk command, the admin action, a plain re-sync
        call_command('classify_schemes', '--apply', stdout=StringIO())
        self.admin_action('fill_level_selected', self.scheme_)
        self.sync({'bank-loan': ('2024-10-01', base.page('Bank Loan v3', table=(('Department', 'Bank of Maharashtra'),)))})
        self.scheme_.refresh_from_db()
        self.assertEqual((self.scheme_.level, self.scheme_.state), ('national', ''))
        self.assertEqual(self.titles('level', 'national'), [self.scheme_.title])

    def test_releasing_local_edits_does_not_hand_the_level_back_to_the_rules(self) -> None:
        self.admin_post(self.scheme_, level='national', state='', title='Edited title')
        self.admin_action('release_local_edits', Scheme.objects.get())
        self.sync({'bank-loan': ('2024-09-01', base.page('Bank Loan', benefits=('Rs. 3',), table=(('Department', 'Bank of Maharashtra'),)))})
        self.assertEqual(Scheme.objects.get().level, 'national')


class BreakItHostileInputTests(BreakItBase):
    """5. Garbage and attacks on the two new filter keys and the options endpoint: always a clean 400 or 200, never a
    crash, never a leak of internals, never a change to the data, and never an answer for the wrong kind of user."""

    def setUp(self) -> None:
        super().setUp()
        self.scheme('Haryana one', level='state', state='Haryana')
        self.scheme('National one', level='national')
        self.before = list(Scheme.objects.order_by('pk').values_list('pk', 'title', 'level', 'state', 'status'))

    def assert_clean(self, response, label: str) -> None:
        self.assertIn(response.status_code, (200, 400), (label, response.status_code))
        body = response.content.decode()
        for leak in ('Traceback', 'SELECT ', 'OperationalError', 'django.', 'File "'):
            self.assertNotIn(leak, body, label)

    def test_bad_values_are_refused_cleanly(self) -> None:
        hostile = [
            "Haryana' OR '1'='1", 'Haryana"; DROP TABLE scheme;--', "' UNION SELECT * FROM users --", '%', '_', '*', '..',
            'Haryаna',                     # a Cyrillic "а" that looks like the real letter
            'Har​yana',               # a zero-width space inside the name
            'Haryana\x00', 'Haryana\n', '<script>alert(1)</script>', '{{7*7}}', '0', '-1', 'null', 'None', 'true',
            'A' * 5000, '😀', 'national OR state', 'state,national', 'Haryana,Punjab', 'ＨＡＲＹＡＮＡ',
        ]
        for value in hostile:
            for key in ('state', 'level'):
                response = self.member_client.get(LIST, {'filter_key': key, 'filter_value': value})
                self.assert_clean(response, f'{key}={value[:30]!r}')
                if key == 'state' and value.strip() == 'Haryana':   # a trailing newline is just whitespace
                    self.assertEqual([r['title'] for r in rows(response)], ['Haryana one'], value)
                else:
                    self.assertEqual(response.status_code, 400, f'{key}={value[:30]!r}')
        self.assertEqual(list(Scheme.objects.order_by('pk').values_list('pk', 'title', 'level', 'state', 'status')), self.before)

    def test_only_a_true_state_name_ever_returns_schemes(self) -> None:
        for value in ("Haryana' OR '1'='1", 'Haryаna', 'Har​yana', '%', 'Haryana\x00', 'Haryana,Punjab'):
            response = self.member_client.get(LIST, {'filter_key': 'state', 'filter_value': value})
            self.assertEqual(response.status_code, 400, value)

    def test_unknown_or_dangerous_keys_are_refused(self) -> None:
        for key in ('State', 'LEVEL', 'status', 'is_manual', 'locally_edited', 'source_url', 'tags__name', 'level__gt', 'state__icontains',
                    '__class__', 'pk', 'reviewed_by__password', 'level; DROP TABLE scheme', ''):
            response = self.member_client.get(LIST, {'filter_key': key, 'filter_value': 'national'}) if key else self.member_client.get(LIST, {'filter_value': 'national'})
            self.assert_clean(response, f'key={key!r}')
            self.assertEqual(response.status_code, 400, key)

    def test_a_key_without_a_value_or_the_reverse_is_refused(self) -> None:
        for params in ({'filter_key': 'level'}, {'filter_value': 'national'}, {'filter_key': 'state', 'filter_value': ''}):
            self.assertEqual(self.member_client.get(LIST, params).status_code, 400, params)

    def test_repeated_and_bad_paging_parameters_never_crash(self) -> None:
        for query in ('filter_key=level&filter_key=state&filter_value=national', 'filter_key=level&filter_value=national&filter_value=state',
                      'filter_key=level&filter_value=national&page_num=0', 'filter_key=level&filter_value=national&page_num=-5',
                      'filter_key=level&filter_value=national&page_num=abc', 'filter_key=level&filter_value=national&limit=0',
                      'filter_key=level&filter_value=national&limit=99999999', 'filter_key=level&filter_value=national&limit=1.5',
                      'filter_key=level&filter_value=national&sort_by=level', 'filter_key=level&filter_value=national&sort_by=password',
                      'filter_key=level&filter_value=national&from_date=99-99-99', 'filter_key=level&filter_value=national&search_key=%27'):
            self.assert_clean(self.member_client.get(f'{LIST}?{query}'), query)

    def test_the_wrong_kind_of_user_gets_nothing(self) -> None:
        for client, expected in ((self.as_user(None), 401), (self.as_user(self.staff('Scheme Reviewers')), 403),
                                 (self.as_user(self.staff('Support Handlers')), 403)):
            for url in (f'{LIST}?filter_key=level&filter_value=national', f'{LIST}?filter_key=state&filter_value=Haryana', OPTIONS):
                self.assertEqual(client.get(url).status_code, expected, url)

    def test_write_methods_cannot_reach_the_new_endpoint_or_filters(self) -> None:
        for method in ('post', 'put', 'patch', 'delete'):
            response = getattr(self.member_client, method)(OPTIONS, {'level': 'national'}, format='json')
            self.assertEqual(response.status_code, 405, method)
        self.assertEqual(list(Scheme.objects.order_by('pk').values_list('pk', 'title', 'level', 'state', 'status')), self.before)

    def test_a_member_cannot_see_internal_fields_through_the_new_columns(self) -> None:
        payload = str(self.member_client.get(OPTIONS).data) + str(rows(self.member_client.get(LIST)))
        for internal in ('contentHash', 'locallyEdited', 'isManual', 'reviewedBy', 'sourceUrl', 'pending_review', 'unpublished'):
            self.assertNotIn(internal, payload)
