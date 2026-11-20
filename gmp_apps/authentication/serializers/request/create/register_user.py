from typing import Any

from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from gmp.constants import Constants
from gmp_apps.authentication.dataclasses.request.create.register_user import RegisterUserRequest
from gmp_apps.authentication.models import User
from gmp_apps.authentication.serializers.request.profile_fields import ExtendedProfileFields
from gmp_apps.authentication.utils import AuthenticationUtils


class RegisterUserRequestSerializer(ExtendedProfileFields):
    full_name = serializers.CharField(max_length=150)
    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    mobile_number = serializers.CharField(max_length=20, required=False, allow_null=True, allow_blank=True)
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    referral_code = serializers.CharField(max_length=16, required=False, allow_null=True, allow_blank=True)
    declaration_accepted = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        email = AuthenticationUtils.normalize_email(attrs.get('email'))
        mobile = AuthenticationUtils.normalize_mobile(attrs.get('mobile_number'))
        if not email and not mobile:
            raise serializers.ValidationError(Constants.identifier_required)
        if mobile and not AuthenticationUtils.is_valid_mobile(mobile):
            raise serializers.ValidationError({'mobile_number': 'Enter a valid mobile number'})
        if email and User.objects.filter(email=email).exists():
            raise serializers.ValidationError({'email': Constants.email_not_unique})
        if mobile and User.objects.filter(mobile_number=mobile).exists():
            raise serializers.ValidationError({'mobile_number': Constants.mobile_not_unique})
        code = (attrs.get('referral_code') or '').strip().upper()
        attrs['referral_code'] = code or None
        if code and not User.is_valid_referrer_code(code):
            raise serializers.ValidationError({'referral_code': Constants.invalid_referral_code})
        candidate = User(full_name=attrs['full_name'], email=email, mobile_number=mobile)
        validate_password(attrs['password'], user=candidate)
        attrs['email'], attrs['mobile_number'] = email, mobile
        return attrs

    def create(self, validated_data: dict[str, Any]) -> RegisterUserRequest:
        return RegisterUserRequest(**validated_data)
