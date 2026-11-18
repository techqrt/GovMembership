from rest_framework.response import Response

from gmp.constants import Constants
from gmp_apps.common.common import Common
from gmp_apps.common.dataclasses.request.get_all import GetAll
from gmp_apps.common.exceptions.errors import NotFoundError
from gmp_apps.common.query import GetAllQuery
from gmp_apps.common.utils import Utils
from gmp_apps.notifications.dataclasses.request.get.get_unread_count import GetUnreadCountRequest
from gmp_apps.notifications.dataclasses.request.update.mark_read import MarkReadRequest
from gmp_apps.notifications.models import Notification
from gmp_apps.notifications.utils import NotificationUtils


class NotificationsNotificationView:
    def __init__(self) -> None:
        self.data_get = 'Data fetched successfully'
        self.data_mark = 'Marked as read'

    @Common().exception_handler
    def get_all_extract(self, params: GetAll) -> Response:
        """The caller's own notifications only (scoped by the token's user, never by a parameter)."""
        queryset = GetAllQuery.apply(
            Notification.objects.filter(user_id=params.user_id), params,
            sort_columns=NotificationUtils.sort_columns,
            filter_columns=NotificationUtils.filter_columns,
            search_columns=NotificationUtils.search_columns,
            default_ordering='-created_date_time',
        )
        rows, total_page = Utils.paginate_queryset(queryset, params.page_num, params.limit)
        data = GetAllQuery.select_values([NotificationUtils.row(n) for n in rows], params)
        page = Utils.add_page_parameter(
            final_data=data, page_num=params.page_num, total_page=total_page, present_url=params.present_url,
        )
        return Response(Utils.success_response_data(message=self.data_get, data=page))

    @Common().exception_handler
    def unread_count_extract(self, params: GetUnreadCountRequest) -> Response:
        return Response(Utils.success_response_data(message=self.data_get, data={'unreadCount': Notification.unread_count(params.user_id)}))

    @Common().exception_handler
    def mark_read_extract(self, params: MarkReadRequest) -> Response:
        if params.notification_id is not None and not Notification.objects.filter(
            notification_id=params.notification_id, user_id=params.user_id,
        ).exists():
            raise NotFoundError(Constants.not_found_item)  # someone else's id looks like a missing one
        marked = Notification.mark_read(params.user_id, None if params.mark_all else params.notification_id)
        data = {'markedCount': marked, 'unreadCount': Notification.unread_count(params.user_id)}
        return Response(Utils.success_response_data(message=self.data_mark, data=data))
