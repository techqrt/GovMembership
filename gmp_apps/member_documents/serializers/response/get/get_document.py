from rest_framework import serializers


class DocumentResponseGetSerializer(serializers.Serializer):
    documentId = serializers.IntegerField()
    documentType = serializers.CharField()
    label = serializers.CharField(allow_blank=True)
    fileName = serializers.CharField()
    contentType = serializers.CharField()
    sizeBytes = serializers.IntegerField()
    createdDateTime = serializers.DateTimeField()
    downloadUrl = serializers.CharField()
