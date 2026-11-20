from rest_framework import serializers


class IdCardPhotoSerializer(serializers.Serializer):
    documentId = serializers.IntegerField()
    downloadUrl = serializers.CharField(help_text='Fetch with your Bearer token; the file is always sent as a download')


class IdCardResponseGetSerializer(serializers.Serializer):
    fullName = serializers.CharField()
    membershipId = serializers.CharField()
    membershipLevel = serializers.ChoiceField(choices=['general', 'active', 'permanent'])
    memberSince = serializers.DateTimeField()
    photo = IdCardPhotoSerializer(allow_null=True, help_text='The member\'s uploaded profile photo, null when none')
