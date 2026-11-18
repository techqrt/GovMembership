from rest_framework import serializers


class DashboardSectionSerializer(serializers.Serializer):
    key = serializers.CharField()
    title = serializers.CharField()
    data = serializers.DictField()


class DashboardResponseGetSerializer(serializers.Serializer):
    sections = DashboardSectionSerializer(many=True)
