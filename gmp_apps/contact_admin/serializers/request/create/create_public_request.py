import re
from typing import Any

from rest_framework import serializers

from gmp.constants import Constants
from gmp_apps.authentication.utils import AuthenticationUtils
from gmp_apps.contact_admin.dataclasses.request.create.create_public_request import CreatePublicRequestRequest
from gmp_apps.contact_admin.models import ContactCategory

# An opening tag, a closing tag, a comment, a doctype or a processing instruction. A plain "<" or ">" in a sentence is fine.
MARKUP = re.compile(r'<\s*[/!?a-zA-Z]')


def reject_markup(value: str) -> str:
    if MARKUP.search(value):
        raise serializers.ValidationError(Constants.contact_no_markup)
    return value


class CreatePublicRequestRequestSerializer(serializers.Serializer):
    # The topic: send problem_type (its name, for example "Schemes"). category_id (its number) still works; if both come, they must agree.
    problem_type = serializers.CharField(max_length=80, required=False, allow_null=True, allow_blank=True)
    category_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    full_name = serializers.CharField(min_length=2, max_length=150)
    email = serializers.EmailField(max_length=254, required=False, allow_null=True, allow_blank=True)
    mobile_number = serializers.CharField(max_length=20, required=False, allow_null=True, allow_blank=True)
    subject = serializers.CharField(max_length=200, required=False, allow_null=True, allow_blank=True)
    description = serializers.CharField(min_length=10, max_length=5000)
    website = serializers.CharField(max_length=200, required=False, allow_null=True, allow_blank=True)

    def validate_category_id(self, value: int) -> int:
        if not ContactCategory.objects.filter(category_id=value, is_active=True).exists():
            raise serializers.ValidationError(Constants.contact_bad_category)
        return value

    def validate_full_name(self, value: str) -> str:
        return reject_markup(value)

    def validate_subject(self, value: str | None) -> str:
        return reject_markup(value or '')

    def validate_description(self, value: str) -> str:
        return reject_markup(value)

    @staticmethod
    def resolve_topic(problem_type: str | None, category_id: int | None) -> int:
        """The id of the chosen active topic, from its name (any capitals, stray spaces) and/or its number."""
        name = ' '.join((problem_type or '').split())
        if not name and not category_id:
            raise serializers.ValidationError({'problem_type': Constants.contact_problem_type_required})
        active = {c.name.lower(): c.category_id for c in ContactCategory.objects.filter(is_active=True)}
        if not name:
            return category_id
        chosen = active.get(name.lower())
        if chosen is None:
            options = ', '.join(c.name for c in ContactCategory.objects.filter(is_active=True))
            raise serializers.ValidationError({'problem_type': f'{Constants.contact_bad_problem_type}: {options}'})
        if category_id and category_id != chosen:
            raise serializers.ValidationError({'problem_type': Constants.contact_problem_type_mismatch})
        return chosen

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs['category_id'] = self.resolve_topic(attrs.pop('problem_type', None), attrs.get('category_id'))
        email = AuthenticationUtils.normalize_email(attrs.get('email'))
        mobile = AuthenticationUtils.normalize_mobile(attrs.get('mobile_number'))
        if not email and not mobile:
            raise serializers.ValidationError(Constants.contact_contact_required)
        if mobile and not AuthenticationUtils.is_valid_mobile(mobile):
            raise serializers.ValidationError({'mobile_number': 'Enter a valid mobile number'})
        attrs['email'], attrs['mobile_number'] = email, mobile
        attrs['subject'] = (attrs.get('subject') or '').strip()
        attrs['website'] = (attrs.get('website') or '').strip()
        return attrs

    def create(self, validated_data: dict[str, Any]) -> CreatePublicRequestRequest:
        return CreatePublicRequestRequest(**validated_data)
