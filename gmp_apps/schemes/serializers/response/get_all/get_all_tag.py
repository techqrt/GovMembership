from rest_framework import serializers


class TagItemSerializer(serializers.Serializer):
    group = serializers.CharField()
    name = serializers.CharField()
    count = serializers.IntegerField()


class TagResponseGetAllSerializer(serializers.Serializer):
    data = TagItemSerializer(many=True)
