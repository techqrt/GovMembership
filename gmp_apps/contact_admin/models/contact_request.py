from datetime import timedelta

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from gmp.config import Configurations
from gmp.constants import Constants
from gmp_apps.authentication.models import User
from gmp_apps.common.exceptions.errors import NotFoundError
from gmp_apps.contact_admin.models.contact_category import ContactCategory
from gmp_apps.notifications.models import Notification, NotificationKind


class RequestStatus(models.TextChoices):
    OPEN = 'open', 'Open'
    IN_PROGRESS = 'in_progress', 'In progress'
    RESOLVED = 'resolved', 'Resolved'
    CLOSED = 'closed', 'Closed'


OPEN_STATUSES = (RequestStatus.OPEN, RequestStatus.IN_PROGRESS)
REPLY_REQUIRED_STATUSES = (RequestStatus.RESOLVED, RequestStatus.CLOSED)


class ContactRequest(models.Model):
    request_id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='contact_requests')
    category = models.ForeignKey(ContactCategory, on_delete=models.PROTECT, related_name='requests')
    subject = models.CharField(max_length=200)
    description = models.TextField(max_length=5000)
    status = models.CharField(max_length=16, choices=RequestStatus.choices, default=RequestStatus.OPEN)
    admin_reply = models.TextField(blank=True, default='')
    replied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='contact_requests_answered',
    )
    replied_date_time = models.DateTimeField(null=True, blank=True)
    created_date_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'contact_request'
        indexes = [models.Index(fields=['user', 'status'])]

    def __str__(self) -> str:
        return f'#{self.request_id} {self.subject}'

    @staticmethod
    def create(user: User, category: ContactCategory, subject: str, description: str) -> 'ContactRequest':
        """Abuse limits: a cap on unresolved requests and a daily cap per member."""
        if ContactRequest.objects.filter(user=user, status__in=OPEN_STATUSES).count() >= Configurations.contact_max_open_requests:
            raise ValueError(Constants.contact_too_many_open)
        since = timezone.now() - timedelta(days=1)
        if ContactRequest.objects.filter(user=user, created_date_time__gte=since).count() >= Configurations.contact_max_per_day:
            raise ValueError(Constants.contact_daily_limit)
        return ContactRequest.objects.create(user=user, category=category, subject=subject, description=description)

    @staticmethod
    def check_response(current_status: str, new_status: str, reply: str) -> None:
        """Rules for an admin response (shared by the admin form and respond())."""
        if current_status == RequestStatus.CLOSED:
            raise ValueError(Constants.contact_closed)
        if new_status not in RequestStatus.values:
            raise ValueError(Constants.contact_bad_status)
        if new_status in REPLY_REQUIRED_STATUSES and not reply.strip():
            raise ValueError(Constants.contact_reply_required)

    @staticmethod
    def respond(request_id: int, admin: User, status: str, reply: str) -> 'ContactRequest':
        """Set status and reply. A reply on an 'open' request moves it to 'in progress'; the reply
        author and time are recorded only when the reply text changes. Closed requests are final."""
        with transaction.atomic():
            item = ContactRequest.objects.select_for_update().filter(pk=request_id).first()
            if item is None:
                raise NotFoundError(Constants.not_found_item)
            reply = reply.strip()
            if reply and status == RequestStatus.OPEN:
                status = RequestStatus.IN_PROGRESS
            ContactRequest.check_response(item.status, status, reply)
            reply_changed = reply != item.admin_reply
            status_changed = status != item.status
            if reply_changed:
                item.admin_reply, item.replied_by, item.replied_date_time = reply, admin, timezone.now()
            item.status = status
            item.save()
            if reply_changed or status_changed:
                label = RequestStatus(status).label.lower()
                Notification.send(
                    item.user_id, NotificationKind.SUPPORT_UPDATE, 'Update on your request',
                    f'"{item.subject[:80]}" is now {label}.' + (' The administration replied.' if reply_changed and reply else ''),
                    'contact_request', item.request_id,
                )
        return item
