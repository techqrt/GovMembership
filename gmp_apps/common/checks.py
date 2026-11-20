from typing import Any

from cryptography.fernet import Fernet
from django.core.checks import Error, Tags, register

from gmp.config import Configurations


@register(Tags.security, deploy=True)
def field_encryption_keys_check(app_configs: Any, **kwargs: Any) -> list[Error]:
    """`manage.py check --deploy` must fail when Aadhaar/PAN encryption is not set up properly."""
    keys = [key.strip() for key in Configurations.field_encryption_keys if key.strip()]
    if not keys:
        return [Error('FIELD_ENCRYPTION_KEYS is not set', hint='Generate a Fernet key and set FIELD_ENCRYPTION_KEYS in the environment.', id='gmp.E001')]
    for key in keys:
        try:
            Fernet(key.encode())
        except ValueError:
            return [Error('FIELD_ENCRYPTION_KEYS contains an invalid key', hint='Each key must be url-safe base64 of 32 bytes (Fernet.generate_key()).', id='gmp.E002')]
    return []
