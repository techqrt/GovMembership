from rest_framework import serializers

from gmp_apps.member_documents.serializers.response.get.get_document import DocumentResponseGetSerializer


class RequestResponseGetSerializer(serializers.Serializer):
    requestId = serializers.IntegerField()
    categoryId = serializers.IntegerField()
    categoryName = serializers.CharField()
    subject = serializers.CharField()
    description = serializers.CharField()
    status = serializers.CharField()
    priority = serializers.CharField()
    attachments = DocumentResponseGetSerializer(many=True)
    adminReply = serializers.CharField(allow_blank=True)
    repliedDateTime = serializers.DateTimeField(allow_null=True)
    createdDateTime = serializers.DateTimeField()
