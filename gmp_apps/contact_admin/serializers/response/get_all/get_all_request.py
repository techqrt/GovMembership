from rest_framework import serializers

from gmp_apps.contact_admin.serializers.response.get.get_category import CategoryResponseGetSerializer
from gmp_apps.contact_admin.serializers.response.get.get_request import RequestResponseGetSerializer


class PageSerializer(serializers.Serializer):
    presentPage = serializers.IntegerField()
    totalPage = serializers.IntegerField()
    nextPageUrl = serializers.CharField(required=False)
    previousPageUrl = serializers.CharField(required=False)


class RequestResponseGetAllSerializer(PageSerializer):
    data = RequestResponseGetSerializer(many=True)


class CategoryResponseGetAllSerializer(PageSerializer):
    data = CategoryResponseGetSerializer(many=True)
