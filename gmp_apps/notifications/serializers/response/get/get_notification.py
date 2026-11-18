from rest_framework import serializers


class NotificationItemSerializer(serializers.Serializer):
    notificationId = serializers.IntegerField()
    kind = serializers.CharField()
    title = serializers.CharField()
    message = serializers.CharField()
    referenceType = serializers.CharField(allow_blank=True)
    referenceId = serializers.IntegerField(allow_null=True)
    isRead = serializers.BooleanField()
    createdDateTime = serializers.DateTimeField()
    readDateTime = serializers.DateTimeField(allow_null=True)


class UnreadCountResponseSerializer(serializers.Serializer):
    unreadCount = serializers.IntegerField()
