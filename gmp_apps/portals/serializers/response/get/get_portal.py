from rest_framework import serializers


class PortalResponseGetSerializer(serializers.Serializer):
    portalId = serializers.IntegerField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    department = serializers.CharField(allow_blank=True)
    categoryId = serializers.IntegerField()
    categoryName = serializers.CharField()
    officialUrl = serializers.CharField()
