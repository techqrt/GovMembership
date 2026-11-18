import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from gmp.config import Configurations
from gmp.constants import Constants


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
        Otp.objects.filter(user_id=user_id, purpose=purpose, channel=channel, is_used=False).update(is_used=True)
        code = Otp.generate_code()
        otp = Otp.objects.create(
            user_id=user_id,
            purpose=purpose,
            channel=channel,
            code_hash=Otp.hash_code(code),
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
        otp.save(update_fields=['is_used'])
        return True
