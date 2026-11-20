import re
import secrets
from typing import Any

CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # no 0/O/1/I
MOBILE_PATTERN = re.compile(r'^\+?[1-9]\d{9,14}$')


class AuthenticationUtils:
    profile_mapper: dict[str, str] = {
        'user_id': 'userId',
        'membership_id': 'membershipId',
        'full_name': 'fullName',
        'email': 'email',
        'mobile_number': 'mobileNumber',
        'email_verified': 'emailVerified',
        'mobile_verified': 'mobileVerified',
        'membership_level': 'membershipLevel',
        'referral_code': 'referralCode',
        'role': 'role',
        'date_of_birth': 'dateOfBirth',
        'gender': 'gender',
        'state': 'state',
        'city': 'city',
        'father_name': 'fatherName',
        'profession': 'profession',
        'area_type': 'areaType',
        'mandal': 'mandal',
        'ward_village': 'wardVillage',
        'house_street': 'houseStreet',
        'pin_code': 'pinCode',
        'app_language': 'appLanguage',
        'declaration_accepted': 'declarationAccepted',
        'declaration_accepted_at': 'declarationAcceptedAt',
        'created_date_time': 'createdDateTime',
    }
    reverse_mapper: dict[str, str] = {camel: snake for snake, camel in profile_mapper.items()}

    @staticmethod
    def random_code(prefix: str, length: int) -> str:
        return prefix + ''.join(secrets.choice(CODE_ALPHABET) for _ in range(length))

    @staticmethod
    def normalize_email(email: str | None) -> str | None:
        return email.strip().lower() if email else None

    @staticmethod
    def normalize_mobile(mobile_number: str | None) -> str | None:
        if not mobile_number:
            return None
        return re.sub(r'[\s\-()]', '', mobile_number)

    @staticmethod
    def is_valid_mobile(mobile_number: str) -> bool:
        return bool(MOBILE_PATTERN.match(mobile_number))

    @staticmethod
    def identifier_channel(identifier: str) -> str:
        return 'email' if '@' in identifier else 'mobile'

    @staticmethod
    def normalize_identifier(identifier: str) -> str:
        if '@' in identifier:
            return identifier.strip().lower()
        return AuthenticationUtils.normalize_mobile(identifier) or ''

    @staticmethod
    def to_camel(row: dict[str, Any]) -> dict[str, Any]:
        return {AuthenticationUtils.profile_mapper.get(key, key): value for key, value in row.items()}

    @staticmethod
    def profile_data(user: Any) -> dict[str, Any]:
        """camelCase profile payload built from an explicit allow-list of columns."""
        row = {column: getattr(user, column) for column in AuthenticationUtils.profile_mapper}
        data = AuthenticationUtils.to_camel(row)
        data['aadhaarNumber'] = user.masked_id('aadhaar')   # masked only: the full numbers are admin-reveal only
        data['panNumber'] = user.masked_id('pan')
        return data
