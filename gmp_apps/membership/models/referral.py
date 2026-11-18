from datetime import timedelta

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from gmp.config import Configurations
from gmp.constants import Constants
from gmp_apps.common.exceptions.errors import NotFoundError
from gmp_apps.notifications.models import Notification, NotificationKind
from gmp_apps.authentication.models import User
from gmp_apps.authentication.models.user import MembershipLevel


class ReferralStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'      # registered, contact not verified yet
    VERIFIED = 'verified', 'Verified'   # counts towards Active
    FLAGGED = 'flagged', 'Flagged'      # fraud check hit, waits for admin review
    REJECTED = 'rejected', 'Rejected'   # decided by admin, never counts


class Referral(models.Model):
    referral_id = models.BigAutoField(primary_key=True)
    referrer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='referrals_made')
    # OneToOne: a person can only ever be referred once (duplicate check enforced by the database).
    referred = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='referral_received')
    status = models.CharField(max_length=16, choices=ReferralStatus.choices, default=ReferralStatus.PENDING)
    flag_reason = models.CharField(max_length=255, blank=True, default='')
    admin_remarks = models.TextField(blank=True, default='')
    verified_date_time = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='referrals_reviewed',
    )
    reviewed_date_time = models.DateTimeField(null=True, blank=True)
    created_date_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'referral'
        indexes = [models.Index(fields=['referrer', 'status'])]

    def __str__(self) -> str:
        return f'{self.referrer_id} -> {self.referred_id} ({self.status})'

    # ---------- registration time: duplicate and fraud checks ----------

    @staticmethod
    def attach(referrer_code: str, referred: User) -> 'Referral':
        referrer = User.objects.filter(referral_code=referrer_code).first()
        return Referral.attach_referrer(referrer=referrer, referred=referred)

    @staticmethod
    def attach_referrer(referrer: User | None, referred: User) -> 'Referral':
        """Create the referral after the duplicate and fraud checks. The referrer must be an active
        member with a verified contact, and cannot be the referred person."""
        usable = referrer is not None and referrer.is_active and (referrer.email_verified or referrer.mobile_verified)
        if not usable or referrer.user_id == referred.user_id:
            raise ValueError(Constants.invalid_referral_code)
        reasons = Referral.fraud_reasons(referrer=referrer, referred=referred)
        return Referral.objects.create(
            referrer=referrer,
            referred=referred,
            status=ReferralStatus.FLAGGED if reasons else ReferralStatus.PENDING,
            flag_reason='; '.join(reasons),
        )

    @staticmethod
    def fraud_reasons(referrer: User, referred: User) -> list[str]:
        """Signals that send a referral to admin review instead of counting it automatically."""
        reasons: list[str] = []
        ip = referred.registration_ip
        if Configurations.referral_flag_same_ip and ip:
            if referrer.registration_ip == ip:
                reasons.append('registered from the same IP as the referrer')
            elif Referral.objects.filter(referrer=referrer, referred__registration_ip=ip).exists():
                reasons.append('registered from the same IP as another referral of this referrer')
        since = timezone.now() - timedelta(days=1)
        recent = Referral.objects.filter(referrer=referrer, created_date_time__gte=since).count()
        if recent >= Configurations.referral_max_per_day:
            reasons.append('too many referrals in 24 hours')
        return reasons

    # ---------- verification and promotion ----------

    @staticmethod
    def on_user_verified(referred: User) -> None:
        """Called when a contact of `referred` is OTP-verified: a pending referral becomes verified."""
        referral = Referral.objects.filter(referred=referred, status=ReferralStatus.PENDING).first()
        if referral is None:
            return
        referral.mark_verified()
        Referral.promote_if_eligible(referral.referrer_id)

    def mark_verified(self, reviewer: User | None = None) -> None:
        self.status = ReferralStatus.VERIFIED
        self.verified_date_time = timezone.now()
        if reviewer:
            self.reviewed_by, self.reviewed_date_time = reviewer, timezone.now()
        self.save()
        verified = Referral.verified_count(self.referrer_id)
        Notification.send(  # no names or contact details of the referred person
            self.referrer_id, NotificationKind.REFERRAL_VERIFIED, 'A referral was verified',
            f'{verified} of {Configurations.active_referrals_required} verified referrals so far.', 'referral', self.referral_id,
        )

    @staticmethod
    def review(referral_id: int, reviewer: User, decision: str, remarks: str = '') -> 'Referral':
        """Admin decision on a flagged referral. Approving does not skip verification: if the
        referred member never verified a contact the referral goes back to pending."""
        if decision not in ('approve', 'reject'):
            raise ValueError('Decision must be approve or reject')
        if decision == 'reject' and not remarks.strip():
            raise ValueError(Constants.remarks_required)
        with transaction.atomic():
            referral = Referral.objects.select_for_update().select_related('referred').filter(pk=referral_id).first()
            if referral is None:
                raise NotFoundError(Constants.not_found_item)
            if referral.status != ReferralStatus.FLAGGED:
                raise ValueError(Constants.referral_not_flagged)
            referral.admin_remarks = remarks
            if decision == 'reject':
                referral.status = ReferralStatus.REJECTED
                referral.reviewed_by, referral.reviewed_date_time = reviewer, timezone.now()
                referral.save()
            elif referral.referred.email_verified or referral.referred.mobile_verified:
                referral.mark_verified(reviewer=reviewer)
                Referral.promote_if_eligible(referral.referrer_id)
            else:
                referral.status = ReferralStatus.PENDING
                referral.reviewed_by, referral.reviewed_date_time = reviewer, timezone.now()
                referral.save()
        return referral

    @staticmethod
    def verified_count(referrer_id: int) -> int:
        """Qualifying referrals: verified, and the referred member is still an active account."""
        return Referral.objects.filter(
            referrer_id=referrer_id, status=ReferralStatus.VERIFIED, referred__is_active=True,
        ).count()

    @staticmethod
    def promote_if_eligible(referrer_id: int) -> bool:
        """General -> Active at the configured number of verified referrals. Never touches Permanent."""
        if Referral.verified_count(referrer_id) < Configurations.active_referrals_required:
            return False
        promoted = User.objects.filter(
            user_id=referrer_id, is_active=True, membership_level=MembershipLevel.GENERAL,
        ).update(membership_level=MembershipLevel.ACTIVE)
        if promoted:
            Notification.send(
                referrer_id, NotificationKind.LEVEL_CHANGED, 'You are now an Active member',
                'Your membership level changed from General to Active. You can now apply for Permanent membership.', 'membership', None,
            )
        return bool(promoted)
