from rest_framework import serializers


class CategoryResponseGetSerializer(serializers.Serializer):
    categoryId = serializers.IntegerField()
    name = serializers.CharField()
