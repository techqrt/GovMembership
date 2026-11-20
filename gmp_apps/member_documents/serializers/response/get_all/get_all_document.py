from rest_framework import serializers

from gmp_apps.member_documents.serializers.response.get.get_document import DocumentResponseGetSerializer


class DocumentResponseGetAllSerializer(serializers.Serializer):
    presentPage = serializers.IntegerField()
    totalPage = serializers.IntegerField()
    nextPageUrl = serializers.CharField(required=False)
    previousPageUrl = serializers.CharField(required=False)
    data = DocumentResponseGetSerializer(many=True)
