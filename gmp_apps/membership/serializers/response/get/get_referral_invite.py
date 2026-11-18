from rest_framework import serializers


class ReferralInviteResponseGetSerializer(serializers.Serializer):
    inviteId = serializers.IntegerField()
    fullName = serializers.CharField()
    email = serializers.EmailField(allow_null=True)
    mobileNumber = serializers.CharField(allow_null=True)
    status = serializers.CharField()
    expiresAt = serializers.DateTimeField()
    referralLink = serializers.CharField()
    createdDateTime = serializers.DateTimeField()
