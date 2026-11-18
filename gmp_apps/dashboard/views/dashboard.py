from rest_framework.response import Response

from gmp_apps.authentication.models import User
from gmp_apps.common.common import Common
from gmp_apps.common.utils import Utils
from gmp_apps.content.models.content_item import levels_visible_to
from gmp_apps.dashboard.builders import BUILDERS, DashboardContext
from gmp_apps.dashboard.dataclasses.request.get.get_dashboard import GetDashboardRequest
from gmp_apps.dashboard.models import DashboardSection


class DashboardDashboardView:
    def __init__(self) -> None:
        self.data_get = 'Data fetched successfully'

    @Common().exception_handler
    def get_extract(self, params: GetDashboardRequest) -> Response:
        """The caller's dashboard: the sections an admin has switched on for their CURRENT level, in the
        admin's order. A section that is off or above the caller's level is neither built nor mentioned."""
        user = User.objects.get(user_id=params.user_id)
        context = DashboardContext(user, params.present_url)
        sections = DashboardSection.objects.filter(is_enabled=True, min_level__in=levels_visible_to(user.membership_level))
        data = [
            {'key': section.key, 'title': section.title, 'data': BUILDERS[section.key](context)}
            for section in sections
            if section.key in BUILDERS
        ]
        return Response(Utils.success_response_data(message=self.data_get, data={'sections': data}))
