from django.db import transaction
from rest_framework.response import Response

from gmp.constants import Constants
from gmp_apps.authentication.models import User
from gmp_apps.authentication.models.user import MembershipLevel
from gmp_apps.common.common import Common
from gmp_apps.common.dataclasses.request.get_all import GetAll
from gmp_apps.common.exceptions.errors import NotFoundError
from gmp_apps.common.query import GetAllQuery
from gmp_apps.common.utils import Utils
from gmp_apps.membership.dataclasses.request.create.create_permanent_application import (
    CreatePermanentApplicationRequest,
)
from gmp_apps.membership.dataclasses.request.get.get_permanent_application import GetPermanentApplicationRequest
from gmp_apps.membership.models import PermanentApplication
from gmp_apps.membership.models.permanent_application import ApplicationStatus
from gmp_apps.membership.utils import MembershipUtils


class MembershipPermanentApplicationView:
    def __init__(self) -> None:
        self.data_create = 'Application submitted successfully'
        self.data_get = 'Data fetched successfully'

    # ---------- member ----------

    @Common().exception_handler
    def create_extract(self, params: CreatePermanentApplicationRequest) -> Response:
        with transaction.atomic():
            user = User.objects.select_for_update().get(user_id=params.user_id)
            if user.membership_level == MembershipLevel.PERMANENT:
                raise ValueError(Constants.application_already_permanent)
            if user.membership_level != MembershipLevel.ACTIVE:
                raise ValueError(Constants.application_active_only)
            if PermanentApplication.objects.filter(user=user, status=ApplicationStatus.PENDING).exists():
                raise ValueError(Constants.application_pending_exists)
            application = PermanentApplication.objects.create(user=user, reason=params.reason)
        return Response(Utils.success_response_data(
            message=self.data_create, data=MembershipUtils.application_row(application),
        ))

    @Common().exception_handler
    def get_extract(self, params: GetPermanentApplicationRequest) -> Response:
        # Filtering by the caller makes another member's id indistinguishable from a missing one (IDOR).
        application = PermanentApplication.objects.filter(
            application_id=params.application_id, user_id=params.user_id,
        ).first()
        if application is None:
            raise NotFoundError(Constants.not_found_item)
        return Response(Utils.success_response_data(
            message=self.data_get, data=MembershipUtils.application_row(application),
        ))

    @Common().exception_handler
    def get_all_extract(self, params: GetAll) -> Response:
        queryset = PermanentApplication.objects.filter(user_id=params.user_id)
        queryset = GetAllQuery.apply(
            queryset, params,
            sort_columns=MembershipUtils.application_sort_columns,
            filter_columns=MembershipUtils.application_filter_columns,
            search_columns=['reason'],
            default_ordering='-created_date_time',
        )
        rows, total_page = Utils.paginate_queryset(queryset, params.page_num, params.limit)
        data = GetAllQuery.select_values([MembershipUtils.application_row(a) for a in rows], params)
        return self._page(data, params, total_page)

    def _page(self, data: list, params: GetAll, total_page: int) -> Response:
        page = Utils.add_page_parameter(
            final_data=data, page_num=params.page_num, total_page=total_page, present_url=params.present_url,
        )
        return Response(Utils.success_response_data(message=self.data_get, data=page))
