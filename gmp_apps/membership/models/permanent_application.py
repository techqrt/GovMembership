from django.conf import settings
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from gmp.constants import Constants
from gmp_apps.authentication.models import User
from gmp_apps.authentication.models.user import MembershipLevel
from gmp_apps.common.exceptions.errors import NotFoundError
from gmp_apps.notifications.models import Notification, NotificationKind


class ApplicationStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    APPROVED = 'approved', 'Approved'
    REJECTED = 'rejected', 'Rejected'


class PermanentApplication(models.Model):
    application_id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='permanent_applications')
    reason = models.TextField()
    status = models.CharField(max_length=16, choices=ApplicationStatus.choices, default=ApplicationStatus.PENDING)
    admin_remarks = models.TextField(blank=True, default='')
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='permanent_applications_reviewed',
    )
    reviewed_date_time = models.DateTimeField(null=True, blank=True)
    created_date_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'permanent_application'
        constraints = [
            models.UniqueConstraint(
                fields=['user'], condition=Q(status='pending'), name='unique_pending_permanent_application_per_user',
            ),
        ]

    def __str__(self) -> str:
        return f'Permanent application {self.application_id} ({self.status})'

    @staticmethod
    def review(application_id: int, reviewer: User, decision: str, remarks: str = '') -> 'PermanentApplication':
        """Permanent is granted only here, by an admin approving a pending application."""
        if decision not in ('approve', 'reject'):
            raise ValueError('Decision must be approve or reject')
        if decision == 'reject' and not remarks.strip():
            raise ValueError(Constants.remarks_required)
        with transaction.atomic():
            application = PermanentApplication.objects.select_for_update().select_related('user').filter(
                pk=application_id,
            ).first()
            if application is None:
                raise NotFoundError(Constants.not_found_item)
            if application.status != ApplicationStatus.PENDING:
                raise ValueError(Constants.application_already_reviewed)
            if decision == 'approve' and not application.user.is_active:
                raise ValueError(Constants.application_user_inactive)
            application.status = ApplicationStatus.APPROVED if decision == 'approve' else ApplicationStatus.REJECTED
            application.admin_remarks = remarks
            application.reviewed_by = reviewer
            application.reviewed_date_time = timezone.now()
            application.save()
            if decision == 'approve':
                User.objects.filter(user_id=application.user_id).update(membership_level=MembershipLevel.PERMANENT)
            approved = decision == 'approve'
            Notification.send(
                application.user_id, NotificationKind.APPLICATION_DECIDED,
                'Your Permanent membership application was approved' if approved else 'Your Permanent membership application was not approved',
                'You are now a Permanent member.' if approved else 'Open the application to read the administration\'s remarks. You may apply again.',
                'permanent_application', application.application_id,
            )
        return application
