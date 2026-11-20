from rest_framework import serializers


class ActiveApplicationsSerializer(serializers.Serializer):
    permanent = serializers.IntegerField(help_text='Pending Permanent applications')
    support = serializers.IntegerField(help_text='Support requests that are open or in progress')
    total = serializers.IntegerField(help_text='permanent + support: the profile badge number')


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
    fatherName = serializers.CharField(allow_blank=True)
    profession = serializers.CharField(allow_blank=True)
    areaType = serializers.CharField(allow_blank=True)
    mandal = serializers.CharField(allow_blank=True)
    wardVillage = serializers.CharField(allow_blank=True)
    houseStreet = serializers.CharField(allow_blank=True)
    pinCode = serializers.CharField(allow_blank=True)
    appLanguage = serializers.CharField(allow_blank=True)
    aadhaarNumber = serializers.CharField(allow_null=True, help_text='Masked: only the last 4 characters, e.g. XXXXXXXX1234. null when not given.')
    panNumber = serializers.CharField(allow_null=True, help_text='Masked: only the last 4 characters, e.g. XXXXXX234F. null when not given.')
    declarationAccepted = serializers.BooleanField()
    declarationAcceptedAt = serializers.DateTimeField(allow_null=True)
    createdDateTime = serializers.DateTimeField()
    activeApplications = ActiveApplicationsSerializer(required=False, help_text='Returned by profile/get only (not by login or update)')
