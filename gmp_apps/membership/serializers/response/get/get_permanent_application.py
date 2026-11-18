from rest_framework import serializers


class PermanentApplicationResponseGetSerializer(serializers.Serializer):
    applicationId = serializers.IntegerField()
    reason = serializers.CharField()
    status = serializers.CharField()
    adminRemarks = serializers.CharField(allow_blank=True)
    createdDateTime = serializers.DateTimeField()
    reviewedDateTime = serializers.DateTimeField(allow_null=True)

