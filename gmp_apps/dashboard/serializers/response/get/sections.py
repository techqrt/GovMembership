"""Documentation only: the exact shape of `data` for every dashboard section key.

The dashboard view builds plain dictionaries (see `dashboard/builders.py`); these serializers are never used
to produce a response. They exist so Swagger shows the frontend what each section holds, and a test pins them
to the real builder output so they cannot drift."""
from rest_framework import serializers


class ProfileSectionData(serializers.Serializer):
    membershipId = serializers.CharField()
    fullName = serializers.CharField()
    email = serializers.CharField(allow_null=True)
    mobileNumber = serializers.CharField(allow_null=True)
    emailVerified = serializers.BooleanField()
    mobileVerified = serializers.BooleanField()
    membershipLevel = serializers.ChoiceField(choices=['general', 'active', 'permanent'])
    memberSince = serializers.DateTimeField()


class PermanentApplicationBrief(serializers.Serializer):
    applicationId = serializers.IntegerField()
    status = serializers.CharField(help_text='pending, approved or rejected')


class MembershipSectionData(serializers.Serializer):
    membershipLevel = serializers.CharField()
    referralCode = serializers.CharField()
    referralLink = serializers.CharField()
    verifiedReferrals = serializers.IntegerField()
    pendingReferrals = serializers.IntegerField()
    requiredReferrals = serializers.IntegerField()
    remainingReferrals = serializers.IntegerField()
    canApplyForPermanent = serializers.BooleanField()
    permanentApplication = PermanentApplicationBrief(allow_null=True, help_text='Latest application, null when none')


class ContentRow(serializers.Serializer):
    contentId = serializers.IntegerField()
    type = serializers.ChoiceField(choices=['announcement', 'post', 'video', 'tutorial', 'org_update'])
    title = serializers.CharField()
    summary = serializers.CharField()
    categoryId = serializers.IntegerField()
    categoryName = serializers.CharField()
    coverImageUrl = serializers.CharField(allow_null=True)
    videoUrl = serializers.CharField(allow_blank=True)
    durationSeconds = serializers.IntegerField(allow_null=True, help_text='Videos only, 1 to 86400; show as mm:ss')
    readMinutes = serializers.IntegerField(allow_null=True, help_text='Minutes to read; null when the item has no body text')
    videoQuality = serializers.CharField(allow_null=True, help_text='sd, hd, full_hd or 4k; videos only')
    videoQualityLabel = serializers.CharField(allow_null=True, help_text='Chip text, e.g. 4K Ultra HD; hide the chip when null')
    isPinned = serializers.BooleanField()
    publishedDateTime = serializers.DateTimeField()


class ContentSectionData(serializers.Serializer):
    total = serializers.IntegerField(help_text='All items the member may read, not only the ones listed')
    items = ContentRow(many=True)


class SchemeTag(serializers.Serializer):
    group = serializers.CharField()
    name = serializers.CharField()


class SchemeRow(serializers.Serializer):
    schemeId = serializers.IntegerField()
    title = serializers.CharField()
    department = serializers.CharField()
    summary = serializers.CharField()
    imageUrl = serializers.CharField(allow_null=True)
    tags = SchemeTag(many=True)
    isActive = serializers.BooleanField(help_text='Active (true) or Closed (false)')
    level = serializers.ChoiceField(choices=['national', 'state'], allow_null=True, help_text='national or state; null when not set yet')
    state = serializers.CharField(allow_null=True, help_text='The state of a state scheme; null otherwise')
    updatedDateTime = serializers.DateTimeField()


class SchemesSectionData(serializers.Serializer):
    total = serializers.IntegerField()
    items = SchemeRow(many=True)


class PortalRow(serializers.Serializer):
    portalId = serializers.IntegerField()
    name = serializers.CharField()
    description = serializers.CharField()
    department = serializers.CharField()
    categoryId = serializers.IntegerField()
    categoryName = serializers.CharField()
    officialUrl = serializers.CharField(help_text='Visit Portal: opens the official site')
    fileComplaintUrl = serializers.CharField(allow_null=True, help_text='Show the File Complaint button only when not null')
    trackStatusUrl = serializers.CharField(allow_null=True, help_text='Show the Track Status button only when not null')


class PortalsSectionData(serializers.Serializer):
    total = serializers.IntegerField()
    items = PortalRow(many=True)


class SupportRequestRow(serializers.Serializer):
    requestId = serializers.IntegerField()
    subject = serializers.CharField()
    categoryName = serializers.CharField()
    status = serializers.CharField(help_text='open, in_progress, resolved or closed')
    hasReply = serializers.BooleanField()
    repliedDateTime = serializers.DateTimeField(allow_null=True)
    createdDateTime = serializers.DateTimeField()


class SupportSectionData(serializers.Serializer):
    openRequests = serializers.IntegerField()
    latest = SupportRequestRow(many=True)


class NotificationRow(serializers.Serializer):
    notificationId = serializers.IntegerField()
    kind = serializers.CharField()
    title = serializers.CharField()
    message = serializers.CharField()
    referenceType = serializers.CharField(allow_blank=True)
    referenceId = serializers.IntegerField(allow_null=True)
    isRead = serializers.BooleanField()
    createdDateTime = serializers.DateTimeField()
    readDateTime = serializers.DateTimeField(allow_null=True)


class NotificationsSectionData(serializers.Serializer):
    unreadCount = serializers.IntegerField()
    latest = NotificationRow(many=True)


class ChatbotSectionData(serializers.Serializer):
    available = serializers.BooleanField(help_text='Hide the chatbot entry when false')


def _section(name: str, key_choices: list[str], data: type[serializers.Serializer]) -> type[serializers.Serializer]:
    return type(name, (serializers.Serializer,), {
        'key': serializers.ChoiceField(choices=key_choices),
        'title': serializers.CharField(help_text='Admin-editable heading'),
        'data': data(),
    })


# key -> data serializer. The dashboard test compares this with the real builders.
SECTION_DATA: dict[str, type[serializers.Serializer]] = {
    'profile': ProfileSectionData,
    'membership': MembershipSectionData,
    'announcements': ContentSectionData,
    'posts': ContentSectionData,
    'videos': ContentSectionData,
    'tutorials': ContentSectionData,
    'org_updates': ContentSectionData,
    'schemes': SchemesSectionData,
    'portals': PortalsSectionData,
    'support': SupportSectionData,
    'notifications': NotificationsSectionData,
    'chatbot': ChatbotSectionData,
}

SECTION_SERIALIZERS: dict[str, type[serializers.Serializer]] = {
    key: _section(f'DashboardSection{"".join(p.title() for p in key.split("_"))}', [key], data) for key, data in SECTION_DATA.items()
}
