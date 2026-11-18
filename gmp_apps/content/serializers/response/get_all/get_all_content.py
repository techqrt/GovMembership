from rest_framework import serializers

from gmp_apps.content.serializers.response.get.get_content import ContentItemSerializer


class ContentResponseGetAllSerializer(serializers.Serializer):
    presentPage = serializers.IntegerField()
    totalPage = serializers.IntegerField()
    nextPageUrl = serializers.CharField(required=False)
    previousPageUrl = serializers.CharField(required=False)
    data = ContentItemSerializer(many=True)


class CategoryItemSerializer(serializers.Serializer):
    categoryId = serializers.IntegerField()
    name = serializers.CharField()
    itemCount = serializers.IntegerField()


class CategoryResponseGetAllSerializer(serializers.Serializer):
    data = CategoryItemSerializer(many=True)
