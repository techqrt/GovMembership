from django.db.models import Count, Q
from rest_framework.response import Response

from gmp.constants import Constants
from gmp_apps.common.common import Common
from gmp_apps.common.dataclasses.request.get_all import GetAll
from gmp_apps.common.exceptions.errors import NotFoundError
from gmp_apps.common.query import GetAllQuery
from gmp_apps.common.utils import Utils
from gmp_apps.portals.dataclasses.request.get.get_categories import GetCategoriesRequest
from gmp_apps.portals.dataclasses.request.get.get_portal import GetPortalRequest
from gmp_apps.portals.models import ComplaintPortal, PortalCategory
from gmp_apps.portals.utils import PortalUtils


def visible_portals():
    """What members may see: active portals in active categories."""
    return ComplaintPortal.objects.filter(is_active=True, category__is_active=True).select_related('category')


class PortalsPortalView:
    def __init__(self) -> None:
        self.data_get = 'Data fetched successfully'

    @Common().exception_handler
    def get_all_extract(self, params: GetAll) -> Response:
        queryset = GetAllQuery.apply(
            visible_portals(), params,
            sort_columns=PortalUtils.sort_columns,
            filter_columns=PortalUtils.filter_columns,
            search_columns=PortalUtils.search_columns,
            default_ordering=('category__sort_order', 'category__name', 'sort_order', 'name'),
        )
        rows, total_page = Utils.paginate_queryset(queryset, params.page_num, params.limit)
        data = GetAllQuery.select_values([PortalUtils.row(p) for p in rows], params)
        page = Utils.add_page_parameter(
            final_data=data, page_num=params.page_num, total_page=total_page, present_url=params.present_url,
        )
        return Response(Utils.success_response_data(message=self.data_get, data=page))

    @Common().exception_handler
    def get_extract(self, params: GetPortalRequest) -> Response:
        # Inactive portals (or portals of inactive categories) look exactly like missing ones.
        portal = visible_portals().filter(portal_id=params.portal_id).first()
        if portal is None:
            raise NotFoundError(Constants.not_found_item)
        return Response(Utils.success_response_data(message=self.data_get, data=PortalUtils.row(portal)))

    @Common().exception_handler
    def get_categories_extract(self, params: GetCategoriesRequest) -> Response:
        """Categories that currently have at least one visible portal, with how many."""
        rows = (
            PortalCategory.objects.filter(is_active=True)
            .annotate(portal_count=Count('portals', filter=Q(portals__is_active=True)))
            .filter(portal_count__gt=0)
            .order_by('sort_order', 'name')
        )
        data = [{'categoryId': c.category_id, 'name': c.name, 'portalCount': c.portal_count} for c in rows]
        return Response(Utils.success_response_data(message=self.data_get, data={'data': data}))
