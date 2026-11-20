from rest_framework import serializers

from gmp_apps.member_documents.serializers.response.get.get_document import DocumentResponseGetSerializer


class PermanentApplicationResponseGetSerializer(serializers.Serializer):
    applicationId = serializers.IntegerField()
    reason = serializers.CharField()
    status = serializers.CharField()
    adminRemarks = serializers.CharField(allow_blank=True)
    declarationAccepted = serializers.BooleanField()
    documents = DocumentResponseGetSerializer(many=True)
    createdDateTime = serializers.DateTimeField()
    reviewedDateTime = serializers.DateTimeField(allow_null=True)

