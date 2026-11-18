import json
import re
import socket
import ssl
import urllib.error
import urllib.request
from typing import Any

from gmp.config import Configurations
from gmp_apps.chatbot.providers.base import ChatProvider, ProviderError, ProviderUnavailable

HOST = 'generativelanguage.googleapis.com'
MODEL_NAME = re.compile(r'^[a-z0-9][a-z0-9.\-]{1,60}$')
MAX_RESPONSE_BYTES = 1_000_000


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise ProviderError('Unexpected redirect from the AI provider')


class GeminiProvider(ChatProvider):
    """Google Gemini over HTTPS (generateContent, JSON output). Only the standard library is used.

    The API key travels in the `x-goog-api-key` header, never in the URL, and never appears in
    messages or logs. The host is fixed. Only the question text and approved knowledge entries are
    ever sent: no member name, email, ID or any other personal detail.
    """

    def __init__(self, opener: urllib.request.OpenerDirector | None = None, api_key: str | None = None, model: str | None = None) -> None:
        self._opener = opener or urllib.request.build_opener(_NoRedirects(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        self._api_key = Configurations.gemini_api_key if api_key is None else api_key
        self._model = Configurations.gemini_model if model is None else model

    def is_configured(self) -> bool:
        return bool(self._api_key) and bool(MODEL_NAME.match(self._model))

    def generate_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        if not self.is_configured():
            raise ProviderError('The AI provider is not configured')
        body = {
            'systemInstruction': {'parts': [{'text': system}]},
            'contents': [{'role': 'user', 'parts': [{'text': user}]}],
            'generationConfig': {
                'responseMimeType': 'application/json',
                'responseJsonSchema': schema,
                'temperature': 0,
                'maxOutputTokens': Configurations.chatbot_max_output_tokens,
            },
        }
        request = urllib.request.Request(
            f'https://{HOST}/v1beta/models/{self._model}:generateContent',
            data=json.dumps(body).encode(), method='POST',
            headers={'Content-Type': 'application/json', 'x-goog-api-key': self._api_key},
        )
        return self._parse(self._send(request))

    def _send(self, request: urllib.request.Request) -> bytes:
        try:
            with self._opener.open(request, timeout=Configurations.chatbot_timeout_seconds) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            if error.code == 429 or error.code >= 500:
                raise ProviderUnavailable(f'AI provider HTTP {error.code}') from None
            raise ProviderError(f'AI provider rejected the request (HTTP {error.code})') from None
        except (urllib.error.URLError, socket.timeout, TimeoutError, ssl.SSLError, ConnectionError):
            raise ProviderUnavailable('AI provider could not be reached') from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ProviderError('AI provider response is too large')
        return raw

    @staticmethod
    def _parse(raw: bytes) -> dict[str, Any]:
        try:
            data = json.loads(raw)
        except ValueError:
            raise ProviderError('AI provider returned something that is not JSON') from None
        blocked = (data.get('promptFeedback') or {}).get('blockReason')
        if blocked:
            raise ProviderError(f'AI provider blocked the prompt ({blocked})')
        candidates = data.get('candidates') or []
        if not candidates:
            raise ProviderError('AI provider returned no candidate')
        finish = candidates[0].get('finishReason')
        if finish not in (None, 'STOP'):
            raise ProviderError(f'AI provider stopped early ({finish})')
        parts = (candidates[0].get('content') or {}).get('parts') or []
        text = ''.join(part.get('text', '') for part in parts if isinstance(part, dict))
        try:
            result = json.loads(text)
        except ValueError:
            raise ProviderError('AI provider output is not valid JSON') from None
        if not isinstance(result, dict):
            raise ProviderError('AI provider output is not a JSON object')
        return result
