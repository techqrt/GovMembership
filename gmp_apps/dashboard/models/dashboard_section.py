from django.core.exceptions import ValidationError
from django.db import models

from gmp_apps.authentication.models.user import MembershipLevel


class SectionKey(models.TextChoices):
    PROFILE = 'profile', 'Profile'
    MEMBERSHIP = 'membership', 'Membership and referrals'
    ANNOUNCEMENTS = 'announcements', 'Announcements'
    POSTS = 'posts', 'Posts'
    VIDEOS = 'videos', 'Videos'
    TUTORIALS = 'tutorials', 'Tutorials'
    ORG_UPDATES = 'org_updates', 'Organisation updates'
    SCHEMES = 'schemes', 'Government initiatives'
    PORTALS = 'portals', 'Complaint portals'
    SUPPORT = 'support', 'Support messages'
    NOTIFICATIONS = 'notifications', 'Notifications'
    CHATBOT = 'chatbot', 'Chatbot'


# A member must always be able to see who they are and where they stand.
LOCKED_SECTIONS = (SectionKey.PROFILE, SectionKey.MEMBERSHIP)


class DashboardSection(models.Model):
    """Admin control of the member dashboard: which sections exist, their order, and the lowest membership
    level that sees each one. Profile and Membership cannot be switched off or restricted."""

    section_id = models.BigAutoField(primary_key=True)
    key = models.CharField(max_length=24, unique=True, choices=SectionKey.choices, editable=False)
    title = models.CharField(max_length=80)
    is_enabled = models.BooleanField(default=True)
    min_level = models.CharField(max_length=16, choices=MembershipLevel.choices, default=MembershipLevel.GENERAL)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'dashboard_section'
        ordering = ['sort_order', 'section_id']

    def __str__(self) -> str:
        return self.title

    def clean(self) -> None:
        if self.key in LOCKED_SECTIONS and (not self.is_enabled or self.min_level != MembershipLevel.GENERAL):
            raise ValidationError(f'The "{self.title}" section cannot be switched off or restricted to a higher level')

    def save(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.clean()  # also enforced outside forms
        super().save(*args, **kwargs)
