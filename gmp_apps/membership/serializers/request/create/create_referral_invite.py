from typing import Any

from rest_framework import serializers

from gmp.constants import Constants
from gmp_apps.authentication.utils import AuthenticationUtils
from gmp_apps.membership.dataclasses.request.create.create_referral_invite import CreateReferralInviteRequest


class CreateReferralInviteRequestSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150)
    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    mobile_number = serializers.CharField(max_length=20, required=False, allow_null=True, allow_blank=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        email = AuthenticationUtils.normalize_email(attrs.get('email'))
        mobile = AuthenticationUtils.normalize_mobile(attrs.get('mobile_number'))
        if not email and not mobile:
            raise serializers.ValidationError(Constants.identifier_required)
        if mobile and not AuthenticationUtils.is_valid_mobile(mobile):
            raise serializers.ValidationError({'mobile_number': 'Enter a valid mobile number'})
        attrs['email'], attrs['mobile_number'] = email, mobile
        return attrs

    def create(self, validated_data: dict[str, Any]) -> CreateReferralInviteRequest:
        return CreateReferralInviteRequest(**validated_data)
