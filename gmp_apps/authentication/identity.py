import re

AADHAAR_PATTERN = re.compile(r'^\d{12}$')
PAN_PATTERN = re.compile(r'^[A-Z]{5}[0-9]{4}[A-Z]$')
PIN_PATTERN = re.compile(r'^\d{6}$')
LANGUAGE_PATTERN = re.compile(r'^[a-z]{2,3}(-[a-z]{2,4})?$')
# A mask as this API returns it (everything but the last 4 characters hidden). A client that sends one back
# unchanged is not changing the number.
MASK_PATTERN = re.compile(r'^X{6,8}[0-9A-Z]{4}$')
KINDS = ('aadhaar', 'pan')


class IdentityUtils:
    @staticmethod
    def normalize_aadhaar(value: str) -> str:
        return re.sub(r'[\s-]', '', value or '')

    @staticmethod
    def normalize_pan(value: str) -> str:
        return re.sub(r'\s', '', value or '').upper()

    @staticmethod
    def normalize(kind: str, value: str) -> str:
        return IdentityUtils.normalize_aadhaar(value) if kind == 'aadhaar' else IdentityUtils.normalize_pan(value)

    @staticmethod
    def is_valid(kind: str, normalized: str) -> bool:
        pattern = AADHAAR_PATTERN if kind == 'aadhaar' else PAN_PATTERN
        return bool(pattern.match(normalized))

    @staticmethod
    def is_mask(value: str) -> bool:
        return bool(MASK_PATTERN.match((value or '').strip().upper()))

    @staticmethod
    def mask(kind: str, last4: str) -> str:
        """Aadhaar XXXXXXXX1234, PAN XXXXXX234F: only the last 4 characters are ever shown."""
        return 'X' * ((12 if kind == 'aadhaar' else 10) - 4) + last4
