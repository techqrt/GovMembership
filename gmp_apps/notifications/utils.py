from typing import Any

from django.db.models import QuerySet

from gmp.constants import Constants
from gmp_apps.notifications.models import Notification


def read_filter(queryset: QuerySet, value: str) -> QuerySet:
    """`isRead` filter: true or false only."""
    lowered = value.strip().lower()
    if lowered not in ('true', 'false', '1', '0'):
        raise ValueError(Constants.bad_filter_value)
    return queryset.filter(is_read=lowered in ('true', '1'))


class NotificationUtils:
    filter_columns: dict[str, Any] = {'isRead': read_filter, 'kind': 'kind'}
    sort_columns: dict[str, str] = {'notificationId': 'notification_id', 'createdDateTime': 'created_date_time'}
    search_columns: list[str] = ['title', 'message']

    @staticmethod
    def row(notification: Notification) -> dict[str, Any]:
        return {
            'notificationId': notification.notification_id,
            'kind': notification.kind,
            'title': notification.title,
            'message': notification.message,
            'referenceType': notification.reference_type,
            'referenceId': notification.reference_id,
            'isRead': notification.is_read,
            'createdDateTime': notification.created_date_time,
            'readDateTime': notification.read_date_time,
        }
