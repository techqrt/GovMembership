import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.utils import timezone

from gmp.config import Configurations
from gmp.constants import Constants
from gmp_apps.common import field_encryption


class OtpPurpose(models.TextChoices):
    REGISTRATION = 'registration', 'Registration'
    PASSWORD_RESET = 'password_reset', 'Password reset'


class OtpChannel(models.TextChoices):
    EMAIL = 'email', 'Email'
    MOBILE = 'mobile', 'Mobile'


class Otp(models.Model):
    otp_id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='otps')
    purpose = models.CharField(max_length=16, choices=OtpPurpose.choices)
    channel = models.CharField(max_length=8, choices=OtpChannel.choices)
    code_hash = models.CharField(max_length=64)
    # Registration OTPs only: the code, encrypted, so an admin can read it out to a member. Wiped as soon as the
    # code is used or replaced; empty for password reset and whenever no encryption key is configured.
    code_encrypted = models.TextField(blank=True, default='')
    attempts = models.PositiveSmallIntegerField(default=0)
    is_used = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    created_date_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'otp'
        indexes = [models.Index(fields=['user', 'purpose', 'channel'])]

    def __str__(self) -> str:
        return f'OTP {self.purpose}/{self.channel} for user {self.user_id}'

    @staticmethod
    def hash_code(code: str) -> str:
        return hmac.new(settings.SECRET_KEY.encode(), code.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def generate_code() -> str:
        return ''.join(secrets.choice('0123456789') for _ in range(Configurations.otp_length))

    @staticmethod
    def encrypted_for_admin(purpose: str, code: str) -> str:
        """Registration codes only. A missing or bad encryption key must never stop the OTP being sent."""
        if purpose != OtpPurpose.REGISTRATION:
            return ''
        try:
            return field_encryption.encrypt(code)
        except ImproperlyConfigured:
            logging.getLogger(__name__).warning('OTP not stored for admin view: no usable FIELD_ENCRYPTION_KEYS')
            return ''

    def code_for_admin(self) -> str | None:
        """The readable code while it is still usable (registration, unused, not expired), else None."""
        if self.purpose != OtpPurpose.REGISTRATION or self.is_used or self.expires_at < timezone.now() or not self.code_encrypted:
            return None
        try:
            return field_encryption.decrypt(self.code_encrypted)
        except (field_encryption.DecryptionError, ImproperlyConfigured):
            return None

    @staticmethod
    def latest(user_id: int, purpose: str, channel: str) -> 'Otp | None':
        return (
            Otp.objects.filter(user_id=user_id, purpose=purpose, channel=channel)
            .order_by('-created_date_time', '-otp_id')
            .first()
        )

    @staticmethod
    def create(user_id: int, purpose: str, channel: str) -> tuple['Otp', str]:
        """Issue a new OTP, invalidating earlier ones. Raises ValueError inside the cooldown."""
        previous = Otp.latest(user_id=user_id, purpose=purpose, channel=channel)
        cooldown = timedelta(seconds=Configurations.otp_resend_cooldown_seconds)
        if previous and timezone.now() - previous.created_date_time < cooldown:
            raise ValueError(Constants.otp_cooldown)
        Otp.objects.filter(user_id=user_id, purpose=purpose, channel=channel, is_used=False).update(is_used=True, code_encrypted='')
        code = Otp.generate_code()
        otp = Otp.objects.create(
            user_id=user_id,
            purpose=purpose,
            channel=channel,
            code_hash=Otp.hash_code(code),
            code_encrypted=Otp.encrypted_for_admin(purpose, code),
            expires_at=timezone.now() + timedelta(minutes=Configurations.otp_ttl_minutes),
        )
        return otp, code

    @staticmethod
    def verify(user_id: int, purpose: str, channel: str, code: str) -> bool:
        """Consume the latest OTP if the code matches. Wrong guesses count against the attempt cap."""
        otp = Otp.latest(user_id=user_id, purpose=purpose, channel=channel)
        if otp is None or otp.is_used or otp.expires_at < timezone.now():
            return False
        if otp.attempts >= Configurations.otp_max_attempts:
            return False
        if not hmac.compare_digest(otp.code_hash, Otp.hash_code(code)):
            otp.attempts += 1
            otp.save(update_fields=['attempts'])
            return False
        otp.is_used = True
        otp.code_encrypted = ''
        otp.save(update_fields=['is_used', 'code_encrypted'])
        return True
