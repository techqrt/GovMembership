from rest_framework import serializers


class SchemeResponseGetSerializer(serializers.Serializer):
    schemeId = serializers.IntegerField()
    title = serializers.CharField()
    department = serializers.CharField(allow_blank=True)
    description = serializers.CharField(allow_blank=True)
    eligibility = serializers.CharField(allow_blank=True)
    benefits = serializers.CharField(allow_blank=True)
    applicationProcedure = serializers.CharField(allow_blank=True)
    requiredDocuments = serializers.CharField(allow_blank=True)
    highlights = serializers.CharField(allow_blank=True)
    contactDetails = serializers.CharField(allow_blank=True)
    overview = serializers.ListField(child=serializers.DictField(child=serializers.CharField()))
    links = serializers.ListField(child=serializers.DictField(child=serializers.CharField()))
    documents = serializers.ListField(child=serializers.DictField())
    additionalSections = serializers.ListField(child=serializers.DictField(child=serializers.CharField()))
    tags = serializers.ListField(child=serializers.DictField(child=serializers.CharField()))
    images = serializers.ListField(child=serializers.URLField())
    isActive = serializers.BooleanField(help_text='true: show Active; false: show Closed (an admin switch)')
    publishedDateTime = serializers.DateTimeField(allow_null=True)
    updatedDateTime = serializers.DateTimeField()
