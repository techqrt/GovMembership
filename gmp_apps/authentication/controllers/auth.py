from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from gmp_apps.authentication.serializers.request.create.change_password import ChangePasswordRequestSerializer
from gmp_apps.authentication.serializers.request.create.forgot_password import ForgotPasswordRequestSerializer
from gmp_apps.authentication.serializers.request.create.login import LoginRequestSerializer
from gmp_apps.authentication.serializers.request.create.logout import LogoutRequestSerializer
from gmp_apps.authentication.serializers.request.create.refresh_token import RefreshTokenRequestSerializer
from gmp_apps.authentication.serializers.request.create.register_user import RegisterUserRequestSerializer
from gmp_apps.authentication.serializers.request.create.resend_otp import ResendOtpRequestSerializer
from gmp_apps.authentication.serializers.request.create.reset_password import ResetPasswordRequestSerializer
from gmp_apps.authentication.serializers.request.create.verify_otp import VerifyOtpRequestSerializer
from gmp_apps.authentication.serializers.response.get.auth_tokens import (
    LoginResponseSerializer,
    RefreshResponseSerializer,
)
from gmp_apps.authentication.views.auth import AuthenticationAuthView
from gmp_apps.common.serializer_validations import SerializerValidations
from gmp_apps.common.swagger import SwaggerPage
from gmp_apps.common.throttles import AuthRateThrottle


class AuthenticationAuthViewController:
    @extend_schema(
        description='Register a member (mobile and/or email). The account starts as General and an OTP is sent to each contact.',
        request=RegisterUserRequestSerializer,
        responses=SwaggerPage.response(description=AuthenticationAuthView().data_register, authenticated=False),
    )
    @api_view(['POST'])
    @permission_classes([AllowAny])
    @throttle_classes([AuthRateThrottle])
    @SerializerValidations(serializer=RegisterUserRequestSerializer).validate
    def register(request: Request) -> Response:
        return AuthenticationAuthView().register_extract(params=request.params)

    @extend_schema(
        description='Verify a mobile number or email with the OTP sent at registration.',
        request=VerifyOtpRequestSerializer,
        responses=SwaggerPage.response(description=AuthenticationAuthView().data_verify, authenticated=False),
    )
    @api_view(['POST'])
    @permission_classes([AllowAny])
    @throttle_classes([AuthRateThrottle])
    @SerializerValidations(serializer=VerifyOtpRequestSerializer).validate
    def verify_otp(request: Request) -> Response:
        return AuthenticationAuthView().verify_otp_extract(params=request.params)

    @extend_schema(
        description='Resend the registration OTP. Answers the same message whether or not the account exists.',
        request=ResendOtpRequestSerializer,
        responses=SwaggerPage.response(description=AuthenticationAuthView().data_otp_sent, authenticated=False),
    )
    @api_view(['POST'])
    @permission_classes([AllowAny])
    @throttle_classes([AuthRateThrottle])
    @SerializerValidations(serializer=ResendOtpRequestSerializer).validate
    def resend_otp(request: Request) -> Response:
        return AuthenticationAuthView().resend_otp_extract(params=request.params)

    @extend_schema(
        description='Login with mobile number or email plus password. The contact used must be verified.',
        request=LoginRequestSerializer,
        responses=SwaggerPage.response(
            description=AuthenticationAuthView().data_login, response=LoginResponseSerializer, authenticated=False,
        ),
    )
    @api_view(['POST'])
    @permission_classes([AllowAny])
    @throttle_classes([AuthRateThrottle])
    @SerializerValidations(serializer=LoginRequestSerializer).validate
    def login(request: Request) -> Response:
        return AuthenticationAuthView().login_extract(params=request.params)

    @extend_schema(
        description='Exchange a refresh token for a new access and refresh token (the old refresh token is revoked).',
        request=RefreshTokenRequestSerializer,
        responses=SwaggerPage.response(
            description=AuthenticationAuthView().data_refresh, response=RefreshResponseSerializer, authenticated=False,
        ),
    )
    @api_view(['POST'])
    @permission_classes([AllowAny])
    @throttle_classes([AuthRateThrottle])
    @SerializerValidations(serializer=RefreshTokenRequestSerializer).validate
    def refresh(request: Request) -> Response:
        return AuthenticationAuthView().refresh_extract(params=request.params)

    @extend_schema(
        description='Logout: revokes the caller\'s refresh token.',
        request=LogoutRequestSerializer,
        responses=SwaggerPage.response(description=AuthenticationAuthView().data_logout),
    )
    @api_view(['POST'])
    @permission_classes([IsAuthenticated])
    @SerializerValidations(serializer=LogoutRequestSerializer).validate
    def logout(request: Request) -> Response:
        return AuthenticationAuthView().logout_extract(params=request.params)

    @extend_schema(
        description='Change password. Requires the current password; all other sessions are revoked and new tokens returned.',
        request=ChangePasswordRequestSerializer,
        responses=SwaggerPage.response(
            description=AuthenticationAuthView().data_change_password, response=RefreshResponseSerializer,
        ),
    )
    @api_view(['POST'])
    @permission_classes([IsAuthenticated])
    @SerializerValidations(serializer=ChangePasswordRequestSerializer).validate
    def change_password(request: Request) -> Response:
        return AuthenticationAuthView().change_password_extract(params=request.params)

    @extend_schema(
        description='Forgot password / account recovery: sends an OTP to a verified contact. Same answer whether or not the account exists.',
        request=ForgotPasswordRequestSerializer,
        responses=SwaggerPage.response(description=AuthenticationAuthView().data_otp_sent, authenticated=False),
    )
    @api_view(['POST'])
    @permission_classes([AllowAny])
    @throttle_classes([AuthRateThrottle])
    @SerializerValidations(serializer=ForgotPasswordRequestSerializer).validate
    def forgot_password(request: Request) -> Response:
        return AuthenticationAuthView().forgot_password_extract(params=request.params)

    @extend_schema(
        description='Reset the password with the OTP from forgot_password. All sessions are revoked.',
        request=ResetPasswordRequestSerializer,
        responses=SwaggerPage.response(description=AuthenticationAuthView().data_reset_password, authenticated=False),
    )
    @api_view(['POST'])
    @permission_classes([AllowAny])
    @throttle_classes([AuthRateThrottle])
    @SerializerValidations(serializer=ResetPasswordRequestSerializer).validate
    def reset_password(request: Request) -> Response:
        return AuthenticationAuthView().reset_password_extract(params=request.params)
