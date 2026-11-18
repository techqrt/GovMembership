from rest_framework import serializers

from gmp_apps.authentication.serializers.response.get.get_profile import ProfileResponseGetSerializer


class LoginResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    user = ProfileResponseGetSerializer()


class RefreshResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
