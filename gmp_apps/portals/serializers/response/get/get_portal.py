from rest_framework import serializers


class PortalResponseGetSerializer(serializers.Serializer):
    portalId = serializers.IntegerField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    department = serializers.CharField(allow_blank=True)
    categoryId = serializers.IntegerField()
    categoryName = serializers.CharField()
    officialUrl = serializers.CharField()
    fileComplaintUrl = serializers.CharField(allow_null=True, help_text='Optional direct link on the official site. The platform only redirects out.')
    trackStatusUrl = serializers.CharField(allow_null=True, help_text='Optional direct link on the official site. The platform only redirects out.')
