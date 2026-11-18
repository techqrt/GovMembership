from rest_framework.response import Response

from gmp_apps.common.common import Common
from gmp_apps.common.dataclasses.request.get_all import GetAll
from gmp_apps.common.query import GetAllQuery
from gmp_apps.common.utils import Utils
from gmp_apps.membership.models import Referral
from gmp_apps.membership.utils import MembershipUtils


class MembershipReferralView:
    def __init__(self) -> None:
        self.data_get = 'Data fetched successfully'

    @Common().exception_handler
    def get_all_extract(self, params: GetAll) -> Response:
        """The caller's own referrals only (scoped by the token's user, never by a parameter)."""
        queryset = Referral.objects.filter(referrer_id=params.user_id).select_related('referred')
        queryset = GetAllQuery.apply(
            queryset, params,
            sort_columns=MembershipUtils.referral_sort_columns,
            filter_columns=MembershipUtils.referral_filter_columns,
            search_columns=['referred__full_name'],
            default_ordering='-created_date_time',
        )
        rows, total_page = Utils.paginate_queryset(queryset, params.page_num, params.limit)
        data = GetAllQuery.select_values([MembershipUtils.member_referral_row(r) for r in rows], params)
        return self._page(data, params, total_page)

    def _page(self, data: list, params: GetAll, total_page: int) -> Response:
        page = Utils.add_page_parameter(
            final_data=data, page_num=params.page_num, total_page=total_page, present_url=params.present_url,
        )
        return Response(Utils.success_response_data(message=self.data_get, data=page))
