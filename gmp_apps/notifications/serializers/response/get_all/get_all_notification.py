from rest_framework import serializers

from gmp_apps.notifications.serializers.response.get.get_notification import NotificationItemSerializer


class NotificationResponseGetAllSerializer(serializers.Serializer):
    presentPage = serializers.IntegerField()
    totalPage = serializers.IntegerField()
    nextPageUrl = serializers.CharField(required=False)
    previousPageUrl = serializers.CharField(required=False)
    data = NotificationItemSerializer(many=True)
