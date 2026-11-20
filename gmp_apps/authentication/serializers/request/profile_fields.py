from rest_framework import serializers

from gmp.constants import Constants
from gmp_apps.authentication.identity import LANGUAGE_PATTERN, PIN_PATTERN, IdentityUtils
from gmp_apps.authentication.models.user import AreaType

OPTIONAL_TEXT = {'required': False, 'allow_blank': True, 'allow_null': True}


class ExtendedProfileFields(serializers.Serializer):
    """Optional profile fields shared by registration and profile update. Every one can be left out;
    blank clears a text value. Aadhaar and PAN are validated here and stored encrypted."""

    father_name = serializers.CharField(max_length=150, **OPTIONAL_TEXT)
    profession = serializers.CharField(max_length=100, **OPTIONAL_TEXT)
    area_type = serializers.ChoiceField(choices=AreaType.choices, **OPTIONAL_TEXT)
    mandal = serializers.CharField(max_length=100, **OPTIONAL_TEXT)
    ward_village = serializers.CharField(max_length=100, **OPTIONAL_TEXT)
    house_street = serializers.CharField(max_length=200, **OPTIONAL_TEXT)
    pin_code = serializers.CharField(max_length=10, **OPTIONAL_TEXT)
    aadhaar_number = serializers.CharField(max_length=20, **OPTIONAL_TEXT)
    pan_number = serializers.CharField(max_length=20, **OPTIONAL_TEXT)
    app_language = serializers.CharField(max_length=10, **OPTIONAL_TEXT)

    def validate_pin_code(self, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if value and not PIN_PATTERN.match(value):
            raise serializers.ValidationError(Constants.invalid_pin_code)
        return value

    def validate_app_language(self, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if value and not LANGUAGE_PATTERN.match(value):
            raise serializers.ValidationError(Constants.invalid_app_language)
        return value

    def validate_aadhaar_number(self, value: str | None) -> str | None:
        return self._government_id('aadhaar', value, Constants.invalid_aadhaar)

    def validate_pan_number(self, value: str | None) -> str | None:
        return self._government_id('pan', value, Constants.invalid_pan)

    @staticmethod
    def _government_id(kind: str, value: str | None, message: str) -> str | None:
        """null (not sent) and a mask echoed back by the client both mean "no change" (None, dropped by
        the view); '' clears the number; anything else must be valid. Never echoes the submitted value."""
        if value is None:
            return None   # null = not sent: leave the stored number alone
        raw = value.strip()
        if not raw:
            return ''
        if IdentityUtils.is_mask(raw):
            return None
        normalized = IdentityUtils.normalize(kind, raw)
        if not IdentityUtils.is_valid(kind, normalized):
            raise serializers.ValidationError(message)
        return normalized
