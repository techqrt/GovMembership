from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from gmp.config import Configurations
from gmp.constants import Constants
from gmp_apps.common.exceptions.errors import NotFoundError
from gmp_apps.authentication.models import User


class InviteStatus(models.TextChoices):
    INVITED = 'invited', 'Invited'          # open: the person can still register and be linked
    REGISTERED = 'registered', 'Registered'
    CANCELLED = 'cancelled', 'Cancelled'    # withdrawn by the referrer (or an admin)
    EXPIRED = 'expired', 'Expired'          # not used within REFERRAL_INVITE_TTL_DAYS


def default_invite_expiry() -> timezone.datetime:
    return timezone.now() + timedelta(days=Configurations.referral_invite_ttl_days)


class ReferralInvite(models.Model):
    """A member's declaration 'I am referring this person'. No message is sent (delivery is out of
    scope); when that person registers with the same contact the Referral is created automatically."""

    invite_id = models.BigAutoField(primary_key=True)
    referrer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='referral_invites')
    full_name = models.CharField(max_length=150)
    email = models.EmailField(null=True, blank=True)
    mobile_number = models.CharField(max_length=16, null=True, blank=True)
    status = models.CharField(max_length=16, choices=InviteStatus.choices, default=InviteStatus.INVITED)
    expires_at = models.DateTimeField(default=default_invite_expiry)
    created_date_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'referral_invite'
        constraints = [
            # one open invitation per contact across all members: the first referrer owns the person
            models.UniqueConstraint(
                fields=['email'], condition=Q(status='invited'), name='unique_open_invite_email',
            ),
            models.UniqueConstraint(
                fields=['mobile_number'], condition=Q(status='invited'), name='unique_open_invite_mobile',
            ),
        ]

    def __str__(self) -> str:
        return f'Invite {self.invite_id} by {self.referrer_id} ({self.status})'

    @staticmethod
    def create(referrer: User, full_name: str, email: str | None, mobile_number: str | None) -> 'ReferralInvite':
        """Duplicate and abuse checks. Refusals about other people are deliberately generic so a
        member cannot probe which contacts are already registered or invited."""
        ReferralInvite.expire_due()
        if email and email == referrer.email or mobile_number and mobile_number == referrer.mobile_number:
            raise ValueError(Constants.cannot_refer)
        if ReferralInvite._is_registered(email, mobile_number):
            raise ValueError(Constants.cannot_refer)
        open_invites = ReferralInvite._open_matching(email, mobile_number)
        if open_invites.filter(referrer=referrer).exists():
            raise ValueError(Constants.already_referred_by_you)
        if open_invites.exists():
            raise ValueError(Constants.cannot_refer)
        since = timezone.now() - timedelta(days=1)
        if ReferralInvite.objects.filter(referrer=referrer, created_date_time__gte=since).count() >= Configurations.referral_max_per_day:
            raise ValueError(Constants.daily_referral_limit)
        return ReferralInvite.objects.create(
            referrer=referrer, full_name=full_name, email=email, mobile_number=mobile_number,
        )

    @staticmethod
    def claim_for(user: User) -> 'ReferralInvite | None':
        """Oldest open invitation matching the new user's contacts, or None."""
        ReferralInvite.expire_due()
        return ReferralInvite._open_matching(user.email, user.mobile_number).order_by('created_date_time', 'pk').first()

    @staticmethod
    def expire_due() -> int:
        """Lazy expiry (no scheduler needed): open invitations past their date become 'expired',
        which also frees the contact for a new invitation."""
        return ReferralInvite.objects.filter(
            status=InviteStatus.INVITED, expires_at__lte=timezone.now(),
        ).update(status=InviteStatus.EXPIRED)

    @staticmethod
    def cancel(invite_id: int, referrer_id: int) -> 'ReferralInvite':
        """Cancel the caller's own open invitation. Another member's id looks like a missing one."""
        ReferralInvite.expire_due()
        invite = ReferralInvite.objects.select_for_update().filter(invite_id=invite_id, referrer_id=referrer_id).first()
        if invite is None:
            raise NotFoundError(Constants.not_found_item)
        if invite.status != InviteStatus.INVITED:
            raise ValueError(Constants.invite_not_cancellable)
        invite.status = InviteStatus.CANCELLED
        invite.save(update_fields=['status'])
        return invite

    @staticmethod
    def mark_registered(user: User) -> None:
        """The person registered (with a code): close any open invitation for their contacts."""
        ReferralInvite._open_matching(user.email, user.mobile_number).update(status=InviteStatus.REGISTERED)

    @staticmethod
    def _contact_filter(email: str | None, mobile_number: str | None) -> Q:
        condition = Q(pk__in=[])  # matches nothing unless a contact is supplied
        if email:
            condition |= Q(email=email)
        if mobile_number:
            condition |= Q(mobile_number=mobile_number)
        return condition

    @staticmethod
    def _open_matching(email: str | None, mobile_number: str | None) -> models.QuerySet:
        return ReferralInvite.objects.filter(
            ReferralInvite._contact_filter(email, mobile_number),
            status=InviteStatus.INVITED, expires_at__gt=timezone.now(),
        )

    @staticmethod
    def _is_registered(email: str | None, mobile_number: str | None) -> bool:
        condition = Q(pk__in=[])
        if email:
            condition |= Q(email=email)
        if mobile_number:
            condition |= Q(mobile_number=mobile_number)
        return User.objects.filter(condition).exists()
