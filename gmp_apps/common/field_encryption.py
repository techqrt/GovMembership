import base64
import hashlib
import hmac
import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.core.exceptions import ImproperlyConfigured

from gmp.config import Configurations

logger = logging.getLogger(__name__)
BLIND_INDEX_CONTEXT = b'gmp-blind-index-v1'


class DecryptionError(Exception):
    """A stored value cannot be decrypted with any configured key (wrong or lost key, or tampering)."""


def _keys() -> list[bytes]:
    keys = [key.strip().encode() for key in Configurations.field_encryption_keys if key.strip()]
    if keys:
        return keys
    if Configurations.debug:  # local development only: a stable key derived from SECRET_KEY, so no setup is needed
        logger.warning('FIELD_ENCRYPTION_KEYS is not set: using a development key derived from SECRET_KEY')
        return [base64.urlsafe_b64encode(hashlib.sha256(Configurations.secret_key.encode() + b'|gmp-field-encryption').digest())]
    raise ImproperlyConfigured('FIELD_ENCRYPTION_KEYS must be set to store Aadhaar or PAN numbers')


def _fernet() -> MultiFernet:
    try:
        return MultiFernet([Fernet(key) for key in _keys()])
    except ValueError as error:  # a malformed key
        raise ImproperlyConfigured('FIELD_ENCRYPTION_KEYS contains an invalid key') from error


def encrypt(plain: str) -> str:
    """Authenticated encryption (Fernet: AES-128-CBC + HMAC-SHA256) with the first configured key."""
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as error:
        raise DecryptionError('Stored value cannot be decrypted with the configured keys') from error


def blind_index(kind: str, plain: str) -> str:
    """Keyed hash of a value, for exact-match lookups without decrypting. Keyed with the LAST (oldest)
    key so adding a new first key during rotation does not change any index; if you ever drop the
    oldest key, run `reencrypt_government_ids`. `kind` keeps Aadhaar and PAN apart."""
    secret = hashlib.sha256(_keys()[-1] + BLIND_INDEX_CONTEXT).digest()
    return hmac.new(secret, f'{kind}:{plain}'.encode(), hashlib.sha256).hexdigest()
