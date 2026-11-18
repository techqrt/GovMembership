from rest_framework import serializers


class StatusResponseSerializer(serializers.Serializer):
    available = serializers.BooleanField()
    maxQuestionChars = serializers.IntegerField()
