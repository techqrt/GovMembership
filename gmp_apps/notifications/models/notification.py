from django.conf import settings
from django.db import models
from django.utils import timezone


class NotificationKind(models.TextChoices):
    REFERRAL_VERIFIED = 'referral_verified', 'Referral verified'
    LEVEL_CHANGED = 'level_changed', 'Membership level changed'
    APPLICATION_DECIDED = 'application_decided', 'Permanent application decided'
    SUPPORT_UPDATE = 'support_update', 'Support request updated'


class Notification(models.Model):
    """An in-app message for one member, created by a real event. Delivery by SMS, email or push is a
    third-party concern and not part of this platform. Wording never contains another member's data."""

    notification_id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    kind = models.CharField(max_length=24, choices=NotificationKind.choices)
    title = models.CharField(max_length=200)
    message = models.CharField(max_length=500)
    reference_type = models.CharField(max_length=32, blank=True, default='')
    reference_id = models.PositiveBigIntegerField(null=True, blank=True)
    is_read = models.BooleanField(default=False)
    read_date_time = models.DateTimeField(null=True, blank=True)
    created_date_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notification'
        ordering = ['-created_date_time', '-notification_id']
        indexes = [models.Index(fields=['user', 'is_read', 'created_date_time'])]

    def __str__(self) -> str:
        return f'{self.kind} for user {self.user_id}'

    @staticmethod
    def send(user_id: int, kind: str, title: str, message: str, reference_type: str = '', reference_id: int | None = None) -> 'Notification':
        return Notification.objects.create(
            user_id=user_id, kind=kind, title=title[:200], message=message[:500],
            reference_type=reference_type, reference_id=reference_id,
        )

    @staticmethod
    def unread_count(user_id: int) -> int:
        return Notification.objects.filter(user_id=user_id, is_read=False).count()

    @staticmethod
    def mark_read(user_id: int, notification_id: int | None = None) -> int:
        """Mark the caller's own notification (or all of theirs) as read. Returns how many changed."""
        queryset = Notification.objects.filter(user_id=user_id, is_read=False)
        if notification_id is not None:
            queryset = queryset.filter(notification_id=notification_id)
        return queryset.update(is_read=True, read_date_time=timezone.now())
