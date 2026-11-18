from rest_framework import serializers


class ContentItemSerializer(serializers.Serializer):
    contentId = serializers.IntegerField()
    type = serializers.CharField()
    title = serializers.CharField()
    summary = serializers.CharField(allow_blank=True)
    categoryId = serializers.IntegerField()
    categoryName = serializers.CharField()
    coverImageUrl = serializers.URLField(allow_null=True)
    videoUrl = serializers.CharField(allow_blank=True)
    isPinned = serializers.BooleanField()
    publishedDateTime = serializers.DateTimeField()


class ContentResponseGetSerializer(ContentItemSerializer):
    body = serializers.CharField(allow_blank=True)
