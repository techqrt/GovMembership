from rest_framework import serializers

from gmp_apps.portals.serializers.response.get.get_portal import PortalResponseGetSerializer


class PortalResponseGetAllSerializer(serializers.Serializer):
    presentPage = serializers.IntegerField()
    totalPage = serializers.IntegerField()
    nextPageUrl = serializers.CharField(required=False)
    previousPageUrl = serializers.CharField(required=False)
    data = PortalResponseGetSerializer(many=True)


class CategoryItemSerializer(serializers.Serializer):
    categoryId = serializers.IntegerField()
    name = serializers.CharField()
    portalCount = serializers.IntegerField()


class CategoryResponseGetAllSerializer(serializers.Serializer):
    data = CategoryItemSerializer(many=True)
