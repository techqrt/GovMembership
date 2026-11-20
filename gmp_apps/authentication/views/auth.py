import logging

from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from gmp.constants import Constants
from gmp_apps.authentication.dataclasses.request.create.change_password import ChangePasswordRequest
from gmp_apps.authentication.dataclasses.request.create.forgot_password import ForgotPasswordRequest
from gmp_apps.authentication.dataclasses.request.create.login import LoginRequest
from gmp_apps.authentication.dataclasses.request.create.logout import LogoutRequest
from gmp_apps.authentication.dataclasses.request.create.refresh_token import RefreshTokenRequest
from gmp_apps.authentication.dataclasses.request.create.register_user import RegisterUserRequest
from gmp_apps.authentication.dataclasses.request.create.resend_otp import ResendOtpRequest
from gmp_apps.authentication.dataclasses.request.create.reset_password import ResetPasswordRequest
from gmp_apps.authentication.dataclasses.request.create.verify_otp import VerifyOtpRequest
from gmp_apps.authentication.models import Otp, User
from gmp_apps.authentication.models.otp import OtpPurpose
from gmp_apps.authentication.utils import AuthenticationUtils
from gmp_apps.common.common import Common
from gmp_apps.membership.models.referral import Referral
from gmp_apps.membership.models.referral_invite import ReferralInvite
from gmp_apps.common.exceptions.errors import ForbiddenError, TokenErrors, ValidationErrors
from gmp_apps.common.utils import Utils

logger = logging.getLogger(__name__)

# Hash of a throwaway password, checked when the account is unknown so timing does not reveal it.
DUMMY_PASSWORD_HASH = 'pbkdf2_sha256$1000000$dummy$' + 'A' * 43


class AuthenticationAuthView:
    def __init__(self) -> None:
        self.data_register = 'Registered. An OTP was sent to verify your contact details'
        self.data_verify = 'Verified successfully'
        self.data_login = 'Login successful'
        self.data_refresh = 'Token refreshed'
        self.data_logout = 'Logged out'
        self.data_change_password = 'Password changed'
        self.data_reset_password = 'Password reset successful'
        self.data_otp_sent = Constants.generic_otp_sent

    # ---------- registration and verification ----------

    @Common().exception_handler
    def register_extract(self, params: RegisterUserRequest) -> Response:
        with transaction.atomic():
            user = User.objects.create_user(
                full_name=params.full_name,
                password=params.password,
                email=params.email,
                mobile_number=params.mobile_number,
                registration_ip=getattr(params, 'client_ip', None),
                **self._profile_extras(params),
            )
            self._store_government_ids(user, params)
            self._link_referral(user=user, referral_code=params.referral_code)
            issued = self._issue_otps_for_channels(user=user)
        for channel, destination, code in issued:
            self._deliver(channel=channel, destination=destination, code=code, purpose=OtpPurpose.REGISTRATION)
        return Response(Utils.success_response_data(
            message=self.data_register, data={'membershipId': user.membership_id},
        ))

    @Common().exception_handler
    def verify_otp_extract(self, params: VerifyOtpRequest) -> Response:
        user = User.find_by_identifier(params.identifier)
        channel = AuthenticationUtils.identifier_channel(params.identifier)
        verified = user is not None and Otp.verify(
            user_id=user.user_id, purpose=OtpPurpose.REGISTRATION, channel=channel, code=params.otp,
        )
        if not verified:
            raise ValueError(Constants.invalid_otp)
        user.mark_channel_verified(channel)
        Referral.on_user_verified(user)
        return Response(Utils.success_response_data(message=self.data_verify))

    @Common().exception_handler
    def resend_otp_extract(self, params: ResendOtpRequest) -> Response:
        user = User.find_by_identifier(params.identifier)
        channel = AuthenticationUtils.identifier_channel(params.identifier)
        if user and user.is_active and not user.is_channel_verified(channel):
            self._send_otp(user=user, channel=channel, purpose=OtpPurpose.REGISTRATION)
        return Response(Utils.success_response_data(message=self.data_otp_sent))

    # ---------- session ----------

    @Common().exception_handler
    def login_extract(self, params: LoginRequest) -> Response:
        user = User.find_by_identifier(params.identifier)
        password_ok = check_password(params.password, user.password if user else DUMMY_PASSWORD_HASH)
        if user is None or not password_ok:
            raise TokenErrors([Constants.invalid_credentials])
        if not user.is_active:
            raise ForbiddenError(Constants.account_inactive)
        channel = AuthenticationUtils.identifier_channel(params.identifier)
        if not user.is_channel_verified(channel):
            raise ForbiddenError(Constants.account_not_verified)
        return Response(Utils.success_response_data(
            message=self.data_login,
            data={**self._tokens(user), 'user': AuthenticationUtils.profile_data(user)},
        ))

    @Common().exception_handler
    def refresh_extract(self, params: RefreshTokenRequest) -> Response:
        try:
            token = RefreshToken(params.refresh)
        except TokenError:
            raise TokenErrors(['Invalid or expired refresh token'])
        user = User.objects.filter(user_id=token['user_id'], is_active=True).first()
        if user is None or token.get('token_version', 0) != user.token_version:
            raise TokenErrors(['Invalid or expired refresh token'])
        token.blacklist()
        return Response(Utils.success_response_data(message=self.data_refresh, data=self._tokens(user)))

    @Common().exception_handler
    def logout_extract(self, params: LogoutRequest) -> Response:
        try:
            token = RefreshToken(params.refresh)
        except TokenError:
            raise ValueError('Invalid or expired refresh token')
        if str(token['user_id']) != str(params.user_id):
            raise ForbiddenError('This token does not belong to you')
        token.blacklist()
        return Response(Utils.success_response_data(message=self.data_logout))

    # ---------- passwords ----------

    @Common().exception_handler
    def change_password_extract(self, params: ChangePasswordRequest) -> Response:
        user = User.objects.get(user_id=params.user_id)
        if not user.check_password(params.old_password):
            raise ValueError(Constants.old_password_wrong)
        self._validate_new_password(password=params.new_password, user=user)
        with transaction.atomic():
            user.set_password(params.new_password)
            user.save(update_fields=['password'])
            user.revoke_all_sessions()
        return Response(Utils.success_response_data(message=self.data_change_password, data=self._tokens(user)))

    @Common().exception_handler
    def forgot_password_extract(self, params: ForgotPasswordRequest) -> Response:
        """Always answers the same message so account existence is not revealed."""
        user = User.find_by_identifier(params.identifier)
        channel = AuthenticationUtils.identifier_channel(params.identifier)
        if user and user.is_active and user.is_channel_verified(channel):
            self._send_otp(user=user, channel=channel, purpose=OtpPurpose.PASSWORD_RESET)
        return Response(Utils.success_response_data(message=self.data_otp_sent))

    @Common().exception_handler
    def reset_password_extract(self, params: ResetPasswordRequest) -> Response:
        user = User.find_by_identifier(params.identifier)
        channel = AuthenticationUtils.identifier_channel(params.identifier)
        verified = user is not None and user.is_active and Otp.verify(
            user_id=user.user_id, purpose=OtpPurpose.PASSWORD_RESET, channel=channel, code=params.otp,
        )
        if not verified:
            raise ValueError(Constants.invalid_otp)
        self._validate_new_password(password=params.new_password, user=user)
        with transaction.atomic():
            user.set_password(params.new_password)
            user.save(update_fields=['password'])
            user.revoke_all_sessions()
        return Response(Utils.success_response_data(message=self.data_reset_password))

    # ---------- helpers ----------

    @staticmethod
    def _link_referral(user: User, referral_code: str | None) -> None:
        """An explicit referral code wins. Otherwise an open invitation for this contact links the
        referral; an unusable inviter (suspended, unverified) is skipped, never an error."""
        if referral_code:
            Referral.attach(referrer_code=referral_code, referred=user)
            ReferralInvite.mark_registered(user)
            return
        invite = ReferralInvite.claim_for(user)
        if invite is None:
            return
        try:
            with transaction.atomic():
                Referral.attach_referrer(referrer=invite.referrer, referred=user)
        except ValueError:
            pass
        invite.status = 'registered'
        invite.save(update_fields=['status'])

    @staticmethod
    def _profile_extras(params: RegisterUserRequest) -> dict[str, object]:
        """Optional plain profile fields given at registration (blank means not given)."""
        names = ('father_name', 'profession', 'area_type', 'mandal', 'ward_village', 'house_street', 'pin_code', 'app_language')
        extras: dict[str, object] = {name: getattr(params, name) for name in names if getattr(params, name)}
        if params.declaration_accepted:
            extras.update(declaration_accepted=True, declaration_accepted_at=timezone.now())
        return extras

    @staticmethod
    def _store_government_ids(user: User, params: RegisterUserRequest) -> None:
        columns: list[str] = []
        for kind, value in (('aadhaar', params.aadhaar_number), ('pan', params.pan_number)):
            if value:
                columns += user.set_government_id(kind, value)
        if columns:
            user.save(update_fields=columns)

    @staticmethod
    def _tokens(user: User) -> dict[str, str]:
        refresh = RefreshToken.for_user(user)
        refresh['token_version'] = user.token_version
        return {'access': str(refresh.access_token), 'refresh': str(refresh)}

    @staticmethod
    def _validate_new_password(password: str, user: User) -> None:
        try:
            validate_password(password, user=user)
        except DjangoValidationError as error:
            raise ValidationErrors(list(error.messages))

    @staticmethod
    def _issue_otps_for_channels(user: User) -> list[tuple[str, str, str]]:
        issued: list[tuple[str, str, str]] = []
        for channel, destination in (('email', user.email), ('mobile', user.mobile_number)):
            if destination:
                _, code = Otp.create(user_id=user.user_id, purpose=OtpPurpose.REGISTRATION, channel=channel)
                issued.append((channel, destination, code))
        return issued

    def _send_otp(self, user: User, channel: str, purpose: str) -> None:
        """Issue and deliver one OTP. Inside the resend cooldown nothing is sent (no error, no leak)."""
        try:
            _, code = Otp.create(user_id=user.user_id, purpose=purpose, channel=channel)
        except ValueError:
            return
        destination = user.email if channel == 'email' else user.mobile_number
        self._deliver(channel=channel, destination=destination, code=code, purpose=purpose)

    @staticmethod
    def _deliver(channel: str, destination: str, code: str, purpose: str) -> None:
        backend = import_string(settings.OTP_DELIVERY_BACKEND)
        backend.send(channel=channel, destination=destination, code=code, purpose=purpose)
