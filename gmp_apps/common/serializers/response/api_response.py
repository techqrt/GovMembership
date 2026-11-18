from rest_framework import serializers


class ApiErrorSerializer(serializers.Serializer):
    status = serializers.BooleanField(default=False)
    message = serializers.CharField()
    error = serializers.ListField()
