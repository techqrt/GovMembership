from rest_framework.response import Response

from gmp_apps.common.common import Common
from gmp_apps.common.dataclasses.request.get_all import GetAll
from gmp_apps.common.query import GetAllQuery
from gmp_apps.common.utils import Utils
from gmp_apps.contact_admin.models import ContactCategory
from gmp_apps.contact_admin.utils import ContactAdminUtils


class ContactAdminCategoryView:
    def __init__(self) -> None:
        self.data_get = 'Data fetched successfully'

    @Common().exception_handler
    def get_all_extract(self, params: GetAll) -> Response:
        """Active categories only; inactive ones exist for old requests but cannot be chosen."""
        queryset = GetAllQuery.apply(
            ContactCategory.objects.filter(is_active=True), params,
            sort_columns=ContactAdminUtils.category_sort_columns,
            filter_columns={},
            search_columns=ContactAdminUtils.category_search_columns,
            default_ordering='sort_order',
        )
        rows, total_page = Utils.paginate_queryset(queryset, params.page_num, params.limit)
        data = GetAllQuery.select_values([ContactAdminUtils.category_row(c) for c in rows], params)
        page = Utils.add_page_parameter(
            final_data=data, page_num=params.page_num, total_page=total_page, present_url=params.present_url,
        )
        return Response(Utils.success_response_data(message=self.data_get, data=page))
