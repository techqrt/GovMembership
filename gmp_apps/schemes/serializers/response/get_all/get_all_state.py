from rest_framework import serializers


class StateItemSerializer(serializers.Serializer):
    level = serializers.ChoiceField(choices=['national', 'state'])
    state = serializers.CharField(allow_null=True, help_text='null on the national row')
    count = serializers.IntegerField(help_text='Published schemes at this level / in this state')


class StateResponseGetAllSerializer(serializers.Serializer):
    data = StateItemSerializer(many=True)
