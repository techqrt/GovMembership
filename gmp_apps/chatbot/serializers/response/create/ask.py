from rest_framework import serializers


class SourceSerializer(serializers.Serializer):
    entryId = serializers.IntegerField()
    question = serializers.CharField()


class LinkSerializer(serializers.Serializer):
    label = serializers.CharField()
    url = serializers.URLField()


class ActionSerializer(serializers.Serializer):
    type = serializers.CharField()


class AskResponseSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=['answer', 'no_answer'])
    reply = serializers.CharField()
    language = serializers.CharField()
    sources = SourceSerializer(many=True)
    links = LinkSerializer(many=True)
    screens = serializers.ListField(child=serializers.CharField())
    actions = ActionSerializer(many=True)
