from rest_framework import serializers


class RequestResponseGetSerializer(serializers.Serializer):
    requestId = serializers.IntegerField()
    categoryId = serializers.IntegerField()
    categoryName = serializers.CharField()
    subject = serializers.CharField()
    description = serializers.CharField()
    status = serializers.CharField()
    adminReply = serializers.CharField(allow_blank=True)
    repliedDateTime = serializers.DateTimeField(allow_null=True)
    createdDateTime = serializers.DateTimeField()
