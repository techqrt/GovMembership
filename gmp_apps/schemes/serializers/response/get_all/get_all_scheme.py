from rest_framework import serializers


class SchemeItemSerializer(serializers.Serializer):
    schemeId = serializers.IntegerField()
    title = serializers.CharField()
    department = serializers.CharField(allow_blank=True)
    summary = serializers.CharField(allow_blank=True)
    imageUrl = serializers.URLField(allow_null=True)
    tags = serializers.ListField(child=serializers.DictField(child=serializers.CharField()))
    isActive = serializers.BooleanField(help_text='true: show Active; false: show Closed (an admin switch)')
    level = serializers.ChoiceField(choices=['national', 'state'], allow_null=True, help_text='national or state; null when not set yet')
    state = serializers.CharField(allow_null=True, help_text='The state of a state scheme; null otherwise')
    updatedDateTime = serializers.DateTimeField()


class SchemeResponseGetAllSerializer(serializers.Serializer):
    presentPage = serializers.IntegerField()
    totalPage = serializers.IntegerField()
    nextPageUrl = serializers.CharField(required=False)
    previousPageUrl = serializers.CharField(required=False)
    data = SchemeItemSerializer(many=True)
