from typing import Any

from django.db.models import Q, QuerySet

from gmp.constants import Constants
from gmp_apps.common.dataclasses.request.get_all import GetAll


class GetAllQuery:
    """Applies the standard get_all parameters to a queryset (filter, search, dates, sort).

    Keys arrive camelCase from clients and are mapped to columns through the entity's own
    allow-lists, so no client-supplied name ever reaches the ORM unchecked. Pagination is
    done at the database level by Utils.paginate_queryset.
    """

    @staticmethod
    def apply(
        queryset: QuerySet,
        params: GetAll,
        sort_columns: dict[str, str],
        filter_columns: dict[str, Any],
        search_columns: list[str],
        default_ordering: str | tuple[str, ...],
    ) -> QuerySet:
        queryset = GetAllQuery._filter(queryset, params, filter_columns)
        queryset = GetAllQuery._search(queryset, params, search_columns)
        queryset = GetAllQuery._dates(queryset, params)
        return GetAllQuery._sort(queryset, params, sort_columns, default_ordering)

    @staticmethod
    def _filter(queryset: QuerySet, params: GetAll, filter_columns: dict[str, Any]) -> QuerySet:
        if not params.filter_key:
            return queryset
        if params.filter_key not in filter_columns:
            raise ValueError(Constants.bad_filter_key)
        target = filter_columns[params.filter_key]
        if callable(target):  # entity-specific filter (e.g. a related table), still allow-listed by key
            return target(queryset, params.filter_value)
        return queryset.filter(**{target: params.filter_value})

    @staticmethod
    def _search(queryset: QuerySet, params: GetAll, search_columns: list[str]) -> QuerySet:
        if not params.search_key:
            return queryset
        condition = Q()
        for column in search_columns:
            condition |= Q(**{f'{column}__icontains': params.search_key})
        return queryset.filter(condition)

    @staticmethod
    def _dates(queryset: QuerySet, params: GetAll) -> QuerySet:
        if params.from_date:
            queryset = queryset.filter(created_date_time__date__gte=params.from_date)
        if params.to_date:
            queryset = queryset.filter(created_date_time__date__lte=params.to_date)
        return queryset

    @staticmethod
    def _sort(
        queryset: QuerySet, params: GetAll, sort_columns: dict[str, str], default_ordering: str | tuple[str, ...],
    ) -> QuerySet:
        if not params.sort_by:
            fields = (default_ordering,) if isinstance(default_ordering, str) else default_ordering
            return queryset.order_by(*fields, '-pk')
        if params.sort_by not in sort_columns:
            raise ValueError(Constants.bad_sort_key)
        prefix = '-' if params.sort_order == 'desc' else ''
        return queryset.order_by(f'{prefix}{sort_columns[params.sort_by]}', '-pk')

    @staticmethod
    def select_values(rows: list[dict[str, Any]], params: GetAll) -> list[dict[str, Any]]:
        """Honour `values`: return only the requested camelCase keys."""
        wanted = params.values_list
        if not wanted:
            return rows
        if rows and any(key not in rows[0] for key in wanted):
            raise ValueError(Constants.bad_values_key)
        return [{key: row[key] for key in wanted} for row in rows]
