from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from gmp_apps.common.permissions import IsMemberRole
from gmp_apps.common.serializer_validations import SerializerValidations
from gmp_apps.common.serializers.request.get_all import GetAllSerializer
from gmp_apps.common.swagger import SwaggerPage
from gmp_apps.notifications.serializers.request.get.get_unread_count import GetUnreadCountRequestSerializer
from gmp_apps.notifications.serializers.request.update.mark_read import MarkReadRequestSerializer
from gmp_apps.notifications.serializers.response.get.get_notification import UnreadCountResponseSerializer
from gmp_apps.notifications.serializers.response.get_all.get_all_notification import NotificationResponseGetAllSerializer
from gmp_apps.notifications.serializers.response.update.mark_read import MarkReadResponseSerializer
from gmp_apps.notifications.views.notification import NotificationsNotificationView

NOTE = 'In-app notifications created by events (referral verified, level change, Permanent application decision, support reply). Own notifications only.'


class NotificationsNotificationViewController:
    @extend_schema(
        description=f'{NOTE} Filter keys: isRead (true/false), kind. Sort keys: notificationId, createdDateTime. Search: title, message. Default: newest first.',
        parameters=SwaggerPage.get_all_parameters(),
        responses=SwaggerPage.response(response=NotificationResponseGetAllSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetAllSerializer).validate
    def get_all(request: Request) -> Response:
        return NotificationsNotificationView().get_all_extract(params=request.params)

    @extend_schema(
        description='Number of unread notifications (cheap to poll).',
        responses=SwaggerPage.response(response=UnreadCountResponseSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetUnreadCountRequestSerializer).validate
    def unread_count(request: Request) -> Response:
        return NotificationsNotificationView().unread_count_extract(params=request.params)

    @extend_schema(
        description='Mark one notification (notification_id) or all of your notifications (mark_all=true) as read. Send exactly one of them. Someone else\'s id returns 404.',
        request=MarkReadRequestSerializer,
        responses=SwaggerPage.response(description='Marked as read', response=MarkReadResponseSerializer),
    )
    @api_view(['PUT'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=MarkReadRequestSerializer).validate
    def mark_read(request: Request) -> Response:
        return NotificationsNotificationView().mark_read_extract(params=request.params)
