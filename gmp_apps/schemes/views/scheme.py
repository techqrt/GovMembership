from django.db.models import Count
from rest_framework.response import Response

from gmp.constants import Constants
from gmp_apps.authentication.models import User
from gmp_apps.common.common import Common
from gmp_apps.common.dataclasses.request.get_all import GetAll
from gmp_apps.common.exceptions.errors import NotFoundError
from gmp_apps.common.query import GetAllQuery
from gmp_apps.common.utils import Utils
from gmp_apps.schemes.dataclasses.request.delete.delete_scheme import DeleteSchemeRequest
from gmp_apps.schemes.dataclasses.request.get.get_scheme import GetSchemeRequest
from gmp_apps.schemes.dataclasses.request.get.get_tags import GetTagsRequest
from gmp_apps.schemes.models import Scheme, SchemeTag
from gmp_apps.schemes.models.scheme import SchemeLevel, SchemeStatus
from gmp_apps.schemes.utils import SchemeUtils


LIST_DEFERRED = ('additional_sections', 'links', 'overview', 'contact_details', 'eligibility', 'application_procedure', 'required_documents')


class SchemesSchemeView:
    def __init__(self) -> None:
        self.data_get = 'Data fetched successfully'
        self.data_delete = 'Scheme deleted from this platform (the source site is untouched)'

    @Common().exception_handler
    def get_all_extract(self, params: GetAll) -> Response:
        queryset = GetAllQuery.apply(
            # The list shows a summary only: skip the large detail columns for every row.
            Scheme.objects.filter(status=SchemeStatus.PUBLISHED).defer(*LIST_DEFERRED).prefetch_related('tags', 'images'), params,
            sort_columns=SchemeUtils.sort_columns,
            filter_columns=SchemeUtils.filter_columns,
            search_columns=SchemeUtils.search_columns,
            default_ordering='-updated_date_time',
        )
        base = SchemeUtils.base_url(params.present_url)
        rows, total_page = Utils.paginate_queryset(queryset, params.page_num, params.limit)
        data = GetAllQuery.select_values([SchemeUtils.list_row(s, base) for s in rows], params)
        page = Utils.add_page_parameter(
            final_data=data, page_num=params.page_num, total_page=total_page, present_url=params.present_url,
        )
        return Response(Utils.success_response_data(message=self.data_get, data=page))

    @Common().exception_handler
    def get_extract(self, params: GetSchemeRequest) -> Response:
        # Unpublished and pending schemes look exactly like missing ones.
        scheme = Scheme.objects.filter(scheme_id=params.scheme_id, status=SchemeStatus.PUBLISHED).prefetch_related('tags', 'images', 'documents').first()
        if scheme is None:
            raise NotFoundError(Constants.not_found_item)
        return Response(Utils.success_response_data(message=self.data_get, data=SchemeUtils.detail_row(scheme, SchemeUtils.base_url(params.present_url))))

    @Common().exception_handler
    def get_tags_extract(self, params: GetTagsRequest) -> Response:
        """Tags in use by published schemes, with counts, so clients can build filters."""
        queryset = SchemeTag.objects.filter(scheme__status=SchemeStatus.PUBLISHED)
        if params.group:
            queryset = queryset.filter(group=params.group)
        rows = queryset.values('group', 'name').annotate(count=Count('scheme')).order_by('group', 'name')
        return Response(Utils.success_response_data(message=self.data_get, data={'data': list(rows)}))

    @Common().exception_handler
    def get_states_extract(self) -> Response:
        """National and per-state counts of published schemes, so clients can build the filter. Only places that have
        at least one published scheme are listed; schemes with no level set yet are in neither."""
        published = Scheme.objects.filter(status=SchemeStatus.PUBLISHED)
        rows = []
        national = published.filter(level=SchemeLevel.NATIONAL).count()
        if national:
            rows.append({'level': SchemeLevel.NATIONAL, 'state': None, 'count': national})
        for row in published.filter(level=SchemeLevel.STATE).values('state').annotate(count=Count('scheme_id')).order_by('state'):
            rows.append({'level': SchemeLevel.STATE, 'state': row['state'], 'count': row['count']})
        return Response(Utils.success_response_data(message=self.data_get, data={'data': rows}))

    @Common().exception_handler
    def delete_extract(self, params: DeleteSchemeRequest) -> Response:
        """Removes the local record (and blocks its re-import); never anything on the source site."""
        if not Scheme.objects.filter(scheme_id=params.scheme_id).exists():
            raise NotFoundError(Constants.not_found_item)
        Scheme.remove(params.scheme_id, User.objects.get(user_id=params.user_id), reason='Deleted through the API')
        return Response(Utils.success_response_data(message=self.data_delete))
