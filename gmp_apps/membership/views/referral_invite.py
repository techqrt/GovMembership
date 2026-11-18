from django.db import transaction
from rest_framework.response import Response

from gmp_apps.authentication.models import User
from gmp_apps.common.common import Common
from gmp_apps.common.dataclasses.request.get_all import GetAll
from gmp_apps.common.query import GetAllQuery
from gmp_apps.common.utils import Utils
from gmp_apps.membership.dataclasses.request.create.create_referral_invite import CreateReferralInviteRequest
from gmp_apps.membership.dataclasses.request.update.cancel_referral_invite import CancelReferralInviteRequest
from gmp_apps.membership.models import ReferralInvite
from gmp_apps.membership.utils import MembershipUtils


class MembershipReferralInviteView:
    def __init__(self) -> None:
        self.data_create = 'Referral recorded. Share your referral link with this person'
        self.data_get = 'Data fetched successfully'
        self.data_cancel = 'Referral cancelled'

    @Common().exception_handler
    def create_extract(self, params: CreateReferralInviteRequest) -> Response:
        """The referrer is always the caller (from the token). Nothing here changes any membership
        level: Active still needs 5 verified referrals once the person registers and verifies."""
        referrer = User.objects.get(user_id=params.user_id)
        invite = ReferralInvite.create(
            referrer=referrer, full_name=params.full_name, email=params.email, mobile_number=params.mobile_number,
        )
        return Response(Utils.success_response_data(
            message=self.data_create, data=MembershipUtils.invite_row(invite, referrer.referral_code),
        ))

    @Common().exception_handler
    def cancel_extract(self, params: CancelReferralInviteRequest) -> Response:
        """Soft cancel: the record stays (status 'cancelled'), the contact is free to be referred
        again, and nothing about any membership level changes."""
        with transaction.atomic():
            invite = ReferralInvite.cancel(invite_id=params.invite_id, referrer_id=params.user_id)
        referrer = User.objects.get(user_id=params.user_id)
        return Response(Utils.success_response_data(
            message=self.data_cancel, data=MembershipUtils.invite_row(invite, referrer.referral_code),
        ))

    @Common().exception_handler
    def get_all_extract(self, params: GetAll) -> Response:
        ReferralInvite.expire_due()
        referrer = User.objects.get(user_id=params.user_id)
        queryset = GetAllQuery.apply(
            ReferralInvite.objects.filter(referrer=referrer), params,
            sort_columns=MembershipUtils.invite_sort_columns,
            filter_columns=MembershipUtils.invite_filter_columns,
            search_columns=MembershipUtils.invite_search_columns,
            default_ordering='-created_date_time',
        )
        rows, total_page = Utils.paginate_queryset(queryset, params.page_num, params.limit)
        data = GetAllQuery.select_values([MembershipUtils.invite_row(r, referrer.referral_code) for r in rows], params)
        page = Utils.add_page_parameter(
            final_data=data, page_num=params.page_num, total_page=total_page, present_url=params.present_url,
        )
        return Response(Utils.success_response_data(message=self.data_get, data=page))
