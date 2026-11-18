from rest_framework import serializers


class ProfileResponseGetSerializer(serializers.Serializer):
    userId = serializers.IntegerField()
    membershipId = serializers.CharField()
    fullName = serializers.CharField()
    email = serializers.EmailField(allow_null=True)
    mobileNumber = serializers.CharField(allow_null=True)
    emailVerified = serializers.BooleanField()
    mobileVerified = serializers.BooleanField()
    membershipLevel = serializers.CharField()
    referralCode = serializers.CharField()
    role = serializers.CharField()
    dateOfBirth = serializers.DateField(allow_null=True)
    gender = serializers.CharField(allow_blank=True)
    state = serializers.CharField(allow_blank=True)
    city = serializers.CharField(allow_blank=True)
    createdDateTime = serializers.DateTimeField()
