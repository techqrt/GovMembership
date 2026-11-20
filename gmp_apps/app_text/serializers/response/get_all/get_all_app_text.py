from rest_framework import serializers


class AppTextResponseGetAllSerializer(serializers.Serializer):
    language = serializers.ChoiceField(choices=['en', 'hi'])
    lastUpdated = serializers.DateTimeField(allow_null=True, help_text='When any string last changed; use it to cache. null when there are none.')
    strings = serializers.DictField(child=serializers.CharField(), help_text='key -> text in the chosen language (Hindi falls back to English per string)')
