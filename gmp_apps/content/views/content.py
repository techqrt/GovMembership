from django.db.models import Count
from rest_framework.response import Response

from gmp.constants import Constants
from gmp_apps.authentication.models import User
from gmp_apps.common.common import Common
from gmp_apps.common.dataclasses.request.get_all import GetAll
from gmp_apps.common.exceptions.errors import NotFoundError
from gmp_apps.common.query import GetAllQuery
from gmp_apps.common.utils import Utils
from gmp_apps.content.dataclasses.request.get.get_categories import GetCategoriesRequest
from gmp_apps.content.dataclasses.request.get.get_content import GetContentRequest
from gmp_apps.content.models import ContentCategory, ContentItem
from gmp_apps.content.utils import ContentUtils


def member_level(user_id: int) -> str:
    """The caller's CURRENT level, read from the database on every request (never from the token)."""
    return User.objects.values_list('membership_level', flat=True).get(user_id=user_id)


class ContentItemView:
    def __init__(self) -> None:
        self.data_get = 'Data fetched successfully'

    @Common().exception_handler
    def get_all_extract(self, params: GetAll) -> Response:
        queryset = GetAllQuery.apply(
            ContentItem.visible_for(member_level(params.user_id)).select_related('category').defer('body'), params,
            sort_columns=ContentUtils.sort_columns,
            filter_columns=ContentUtils.filter_columns,
            search_columns=ContentUtils.search_columns,
            default_ordering=('-is_pinned', '-publish_at'),
        )
        base = Utils.public_base_url(params.present_url)
        rows, total_page = Utils.paginate_queryset(queryset, params.page_num, params.limit)
        data = GetAllQuery.select_values([ContentUtils.row(i, base) for i in rows], params)
        page = Utils.add_page_parameter(
            final_data=data, page_num=params.page_num, total_page=total_page, present_url=params.present_url,
        )
        return Response(Utils.success_response_data(message=self.data_get, data=page))

    @Common().exception_handler
    def get_extract(self, params: GetContentRequest) -> Response:
        # Content above the caller's level, drafts, scheduled and expired items all look like missing ones.
        item = ContentItem.visible_for(member_level(params.user_id)).select_related('category').filter(content_id=params.content_id).first()
        if item is None:
            raise NotFoundError(Constants.not_found_item)
        base = Utils.public_base_url(params.present_url)
        return Response(Utils.success_response_data(message=self.data_get, data=ContentUtils.row(item, base, with_body=True)))

    @Common().exception_handler
    def get_categories_extract(self, params: GetCategoriesRequest) -> Response:
        """Categories that hold at least one item this member may read, with how many (for filters)."""
        visible = ContentItem.visible_for(member_level(params.user_id))
        counts = dict(visible.values_list('category_id').annotate(total=Count('content_id')).order_by())
        categories = ContentCategory.objects.filter(is_active=True, category_id__in=list(counts)).order_by('sort_order', 'name')
        data = [{'categoryId': c.category_id, 'name': c.name, 'itemCount': counts[c.category_id]} for c in categories]
        return Response(Utils.success_response_data(message=self.data_get, data={'data': data}))
