from rest_framework import serializers

from gmp_apps.contact_admin.serializers.response.get.get_category import CategoryResponseGetSerializer


class PublicCategoryResponseGetAllSerializer(serializers.Serializer):
    data = CategoryResponseGetSerializer(many=True)
