from rest_framework import serializers


class ProgressApplicationSerializer(serializers.Serializer):
    applicationId = serializers.IntegerField()
    status = serializers.CharField()


class ProgressResponseGetSerializer(serializers.Serializer):
    membershipLevel = serializers.CharField()
    referralCode = serializers.CharField()
    referralLink = serializers.CharField()
    verifiedReferrals = serializers.IntegerField()
    pendingReferrals = serializers.IntegerField()
    requiredReferrals = serializers.IntegerField()
    remainingReferrals = serializers.IntegerField()
    canApplyForPermanent = serializers.BooleanField()
    permanentApplication = ProgressApplicationSerializer(allow_null=True)
