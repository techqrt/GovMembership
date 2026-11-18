from rest_framework import serializers


class MarkReadResponseSerializer(serializers.Serializer):
    markedCount = serializers.IntegerField()
    unreadCount = serializers.IntegerField()
