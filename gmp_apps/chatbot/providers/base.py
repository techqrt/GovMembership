from typing import Any


class ProviderError(Exception):
    """The AI provider could not give a usable answer (blocked, malformed, bad configuration)."""


class ProviderUnavailable(ProviderError):
    """The provider is temporarily out of reach (network, timeout, rate limit, server error)."""


class ChatProvider:
    """What the chatbot needs from an AI provider: one call that returns a JSON object.

    The chatbot never relies on the provider for facts: it only asks it to choose between approved
    entries and to translate approved text, and checks everything that comes back.
    """

    def is_configured(self) -> bool:
        raise NotImplementedError

    def generate_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
