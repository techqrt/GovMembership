from django.conf import settings
from django.test import Client, SimpleTestCase, override_settings

from gmp.config import Configurations

ALLOWED = 'https://members.example.gov.in'


class CorsTests(SimpleTestCase):
    def get(self, path: str, origin: str | None, **extra):
        headers = {'HTTP_ORIGIN': origin} if origin else {}
        return Client().get(path, **headers, **extra)

    def test_safe_defaults(self) -> None:
        self.assertFalse(settings.CORS_ALLOW_ALL_ORIGINS)
        self.assertFalse(settings.CORS_ALLOW_CREDENTIALS)
        self.assertEqual(Configurations.cors_allowed_origins, [])    # nothing allowed unless the environment says so

    @override_settings(CORS_ALLOWED_ORIGINS=[])
    def test_no_origin_is_allowed_when_none_are_configured(self) -> None:
        self.assertNotIn('Access-Control-Allow-Origin', self.get('/api/schema/', ALLOWED))

    @override_settings(CORS_ALLOWED_ORIGINS=[ALLOWED])
    def test_a_listed_origin_is_allowed_and_nothing_else(self) -> None:
        response = self.get('/api/schema/', ALLOWED)
        self.assertEqual(response['Access-Control-Allow-Origin'], ALLOWED)
        self.assertNotIn('Access-Control-Allow-Credentials', response)
        for other in ('https://evil.example', f'{ALLOWED}.evil.example', 'http://members.example.gov.in', 'https://sub.members.example.gov.in', 'null'):
            self.assertNotIn('Access-Control-Allow-Origin', self.get('/api/schema/', other), other)
        self.assertNotIn('Access-Control-Allow-Origin', self.get('/api/schema/', None))

    @override_settings(CORS_ALLOWED_ORIGINS=[ALLOWED])
    def test_preflight_allows_the_authorization_header_for_listed_origins_only(self) -> None:
        def preflight(origin: str):
            return Client().options('/chatbot/ask/', HTTP_ORIGIN=origin, HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST',
                                    HTTP_ACCESS_CONTROL_REQUEST_HEADERS='authorization,content-type')

        ok = preflight(ALLOWED)
        self.assertEqual(ok['Access-Control-Allow-Origin'], ALLOWED)
        self.assertIn('authorization', ok['Access-Control-Allow-Headers'].lower())
        self.assertIn('POST', ok['Access-Control-Allow-Methods'])
        self.assertNotIn('Access-Control-Allow-Origin', preflight('https://evil.example'))

    @override_settings(CORS_ALLOWED_ORIGINS=[ALLOWED])
    def test_the_admin_site_is_never_cross_origin(self) -> None:
        self.assertNotIn('Access-Control-Allow-Origin', self.get('/admin/login/', ALLOWED))
