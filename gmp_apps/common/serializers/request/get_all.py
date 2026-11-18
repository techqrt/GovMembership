from typing import Any

from rest_framework import serializers

from gmp.config import Configurations
from gmp_apps.common.dataclasses.request.get_all import GetAll

DATE_FORMAT = '%d-%m-%y'


class GetAllSerializer(serializers.Serializer):
    """Standard list parameters shared by every get_all endpoint (PMS convention)."""

    values = serializers.CharField(required=False, allow_blank=True, default='')
    page_num = serializers.IntegerField(required=False, min_value=1, default=1)
    limit = serializers.IntegerField(
        required=False, min_value=1, max_value=Configurations.max_page_limit, default=Configurations.pagination_count,
    )
    sort_by = serializers.CharField(required=False, allow_blank=True, default='')
    sort_order = serializers.ChoiceField(choices=['asc', 'desc'], required=False, default='asc')
    filter_key = serializers.CharField(required=False, allow_blank=True, default='')
    filter_value = serializers.CharField(required=False, allow_blank=True, default='')
    search_key = serializers.CharField(required=False, allow_blank=True, default='')
    from_date = serializers.DateField(input_formats=[DATE_FORMAT], required=False, allow_null=True, default=None)
    to_date = serializers.DateField(input_formats=[DATE_FORMAT], required=False, allow_null=True, default=None)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if bool(attrs['filter_key']) != bool(attrs['filter_value']):
            raise serializers.ValidationError('filter_key and filter_value must be sent together')
        if attrs['from_date'] and attrs['to_date'] and attrs['from_date'] > attrs['to_date']:
            raise serializers.ValidationError('from_date cannot be after to_date')
        return attrs

    def create(self, validated_data: dict[str, Any]) -> GetAll:
        return GetAll(**validated_data)
