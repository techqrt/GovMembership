from drf_spectacular.utils import PolymorphicProxySerializer
from rest_framework import serializers

from gmp_apps.dashboard.serializers.response.get.sections import SECTION_SERIALIZERS


class DashboardResponseGetSerializer(serializers.Serializer):
    sections = PolymorphicProxySerializer(
        component_name='DashboardSection',
        serializers=SECTION_SERIALIZERS,
        resource_type_field_name='key',
        many=True,
    )
