from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from gmp_apps.common.permissions import IsMemberRole
from gmp_apps.common.serializer_validations import SerializerValidations
from gmp_apps.common.swagger import SwaggerPage
from gmp_apps.dashboard.serializers.request.get.get_dashboard import GetDashboardRequestSerializer
from gmp_apps.dashboard.serializers.response.get.get_dashboard import DashboardResponseGetSerializer
from gmp_apps.dashboard.views.dashboard import DashboardDashboardView


class DashboardDashboardViewController:
    @extend_schema(
        description=(
            'The member\'s whole dashboard in one call, as an ordered list of sections: profile, membership (level, referral '
            'progress, Permanent application), announcements, posts, videos, tutorials, organisation updates, government '
            'initiatives, complaint portals, support messages, notifications and chatbot access. Each content/list section has '
            '`total` and the latest few `items` (summaries; open the full item through its own endpoint). Only sections an admin '
            'has switched on for the caller\'s current membership level are returned, and content is filtered by the same level '
            'and schedule rules as the content API.'
        ),
        responses=SwaggerPage.response(response=DashboardResponseGetSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetDashboardRequestSerializer).validate
    def get(request: Request) -> Response:
        return DashboardDashboardView().get_extract(params=request.params)
