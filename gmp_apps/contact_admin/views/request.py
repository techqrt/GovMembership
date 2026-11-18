from rest_framework.response import Response

from gmp.constants import Constants
from gmp_apps.authentication.models import User
from gmp_apps.common.common import Common
from gmp_apps.common.dataclasses.request.get_all import GetAll
from gmp_apps.common.exceptions.errors import NotFoundError
from gmp_apps.common.query import GetAllQuery
from gmp_apps.common.utils import Utils
from gmp_apps.contact_admin.dataclasses.request.create.create_request import CreateRequestRequest
from gmp_apps.contact_admin.dataclasses.request.get.get_request import GetRequestRequest
from gmp_apps.contact_admin.models import ContactCategory, ContactRequest
from gmp_apps.contact_admin.utils import ContactAdminUtils


class ContactAdminRequestView:
    def __init__(self) -> None:
        self.data_create = 'Your request was sent to the administration'
        self.data_get = 'Data fetched successfully'

    @Common().exception_handler
    def create_extract(self, params: CreateRequestRequest) -> Response:
        """The sender is always the caller (from the token); status starts as 'open' and the reply
        fields cannot be set by a member."""
        user = User.objects.get(user_id=params.user_id)
        category = ContactCategory.objects.get(category_id=params.category_id, is_active=True)
        item = ContactRequest.create(user=user, category=category, subject=params.subject.strip(), description=params.description.strip())
        return Response(Utils.success_response_data(message=self.data_create, data=ContactAdminUtils.request_row(item)))

    @Common().exception_handler
    def get_extract(self, params: GetRequestRequest) -> Response:
        # Filtering by the caller makes another member's id look like a missing one (IDOR).
        item = ContactRequest.objects.select_related('category').filter(
            request_id=params.request_id, user_id=params.user_id,
        ).first()
        if item is None:
            raise NotFoundError(Constants.not_found_item)
        return Response(Utils.success_response_data(message=self.data_get, data=ContactAdminUtils.request_row(item)))

    @Common().exception_handler
    def get_all_extract(self, params: GetAll) -> Response:
        queryset = ContactRequest.objects.filter(user_id=params.user_id).select_related('category')
        queryset = GetAllQuery.apply(
            queryset, params,
            sort_columns=ContactAdminUtils.request_sort_columns,
            filter_columns=ContactAdminUtils.request_filter_columns,
            search_columns=ContactAdminUtils.request_search_columns,
            default_ordering='-created_date_time',
        )
        rows, total_page = Utils.paginate_queryset(queryset, params.page_num, params.limit)
        data = GetAllQuery.select_values([ContactAdminUtils.request_row(r) for r in rows], params)
        page = Utils.add_page_parameter(
            final_data=data, page_num=params.page_num, total_page=total_page, present_url=params.present_url,
        )
        return Response(Utils.success_response_data(message=self.data_get, data=page))
