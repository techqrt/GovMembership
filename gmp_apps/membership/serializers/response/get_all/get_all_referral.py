from rest_framework import serializers


class PageSerializer(serializers.Serializer):
    presentPage = serializers.IntegerField()
    totalPage = serializers.IntegerField()
    nextPageUrl = serializers.CharField(required=False)
    previousPageUrl = serializers.CharField(required=False)


class ReferralItemSerializer(serializers.Serializer):
    referralId = serializers.IntegerField()
    referredFirstName = serializers.CharField()
    status = serializers.CharField()
    createdDateTime = serializers.DateTimeField()
    verifiedDateTime = serializers.DateTimeField(allow_null=True)


class ReferralResponseGetAllSerializer(PageSerializer):
    data = ReferralItemSerializer(many=True)

