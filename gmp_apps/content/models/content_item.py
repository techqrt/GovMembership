import math

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q, QuerySet
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone

from gmp.config import Configurations

from gmp_apps.authentication.models.user import MembershipLevel
from gmp_apps.common.media import ALLOWED_TYPES_TEXT, sha256_of, sniff_image_extension
from gmp_apps.content.models.content_category import ContentCategory
from gmp_apps.content.validators import validate_cover_upload, validate_video_url

# Higher number = higher membership level. A member sees content whose minimum level is at or below theirs.
LEVEL_RANK = {MembershipLevel.GENERAL: 0, MembershipLevel.ACTIVE: 1, MembershipLevel.PERMANENT: 2}


def levels_visible_to(member_level: str) -> list[str]:
    rank = LEVEL_RANK.get(member_level, 0)
    return [level for level, value in LEVEL_RANK.items() if value <= rank]


class ContentType(models.TextChoices):
    POST = 'post', 'Post'
    ANNOUNCEMENT = 'announcement', 'Announcement'
    VIDEO = 'video', 'Video'
    TUTORIAL = 'tutorial', 'Tutorial'
    ORG_UPDATE = 'org_update', 'Organisation update'


class ContentStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    PUBLISHED = 'published', 'Published'
    ARCHIVED = 'archived', 'Archived'


def cover_upload_path(instance: 'ContentItem', filename: str) -> str:
    return f'content/{filename}'


class ContentItem(models.Model):
    """A post, announcement, video, tutorial or organisation update.

    Visibility to members = published AND go-live time reached AND not expired AND the member's level is
    at least `min_level` AND the category is active. Scheduling needs no background job: it is evaluated
    when members ask. Bodies are plain text only.
    """

    content_id = models.BigAutoField(primary_key=True)
    content_type = models.CharField(max_length=16, choices=ContentType.choices, default=ContentType.POST)
    title = models.CharField(max_length=200)
    summary = models.CharField(max_length=500, blank=True, default='')
    body = models.TextField(max_length=20000, blank=True, default='')
    category = models.ForeignKey(ContentCategory, on_delete=models.PROTECT, related_name='items')
    cover_image = models.FileField(upload_to=cover_upload_path, validators=[validate_cover_upload], blank=True, max_length=255)
    video_url = models.CharField(max_length=500, blank=True, default='', validators=[validate_video_url])
    # Length of a video item in seconds, typed by the editor (videos are only linked, never hosted here).
    # Calculated from the body whenever the item is saved (so list views never have to load the long body).
    read_minutes = models.PositiveSmallIntegerField(null=True, blank=True, editable=False)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(86400)])
    min_level = models.CharField(max_length=16, choices=MembershipLevel.choices, default=MembershipLevel.GENERAL)
    status = models.CharField(max_length=16, choices=ContentStatus.choices, default=ContentStatus.DRAFT)
    is_pinned = models.BooleanField(default=False)
    publish_at = models.DateTimeField(null=True, blank=True)   # go-live time; set to "now" when published without one
    expire_at = models.DateTimeField(null=True, blank=True)    # hidden from members after this time
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='content_created')
    created_date_time = models.DateTimeField(auto_now_add=True)
    updated_date_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'content_item'
        ordering = ['-is_pinned', '-publish_at', '-content_id']
        permissions = [('publish_contentitem', 'Can publish, unpublish or archive content')]
        indexes = [models.Index(fields=['status', 'publish_at'])]

    def __str__(self) -> str:
        return self.title

    # ---------- visibility ----------

    @staticmethod
    def live(now=None) -> QuerySet:
        """Published, gone live and not expired, for every membership level."""
        now = now or timezone.now()
        return ContentItem.objects.filter(
            status=ContentStatus.PUBLISHED, publish_at__lte=now, category__is_active=True,
        ).filter(Q(expire_at__isnull=True) | Q(expire_at__gt=now))

    @staticmethod
    def visible_for(member_level: str, now=None) -> QuerySet:
        """What a member of `member_level` may see. Anything above their level is not returned at all."""
        return ContentItem.live(now).filter(min_level__in=levels_visible_to(member_level))

    def state(self, now=None) -> str:
        now = now or timezone.now()
        if self.status == ContentStatus.ARCHIVED:
            return 'archived'
        if self.status == ContentStatus.DRAFT:
            return 'draft'
        if self.publish_at and self.publish_at > now:
            return 'scheduled'
        if self.expire_at and self.expire_at <= now:
            return 'expired'
        return 'live'

    @staticmethod
    def estimate_read_minutes(body: str) -> int | None:
        """Minutes to read `body` (words / words per minute, at least 1); None when there is no text."""
        words = len(body.split())
        return max(1, math.ceil(words / Configurations.content_read_words_per_minute)) if words else None

    # ---------- validation ----------

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if self.content_type == ContentType.VIDEO and not self.video_url:
            errors['video_url'] = 'A video needs a video link'
        if self.duration_seconds is not None and self.content_type != ContentType.VIDEO:
            errors['duration_seconds'] = 'Duration is only for video items'
        if self.publish_at and self.expire_at and self.expire_at <= self.publish_at:
            errors['expire_at'] = 'Expiry must be after the go-live time'
        if self.status == ContentStatus.PUBLISHED and not (self.body.strip() or self.summary.strip() or self.video_url):
            errors['body'] = 'Add a body, summary or video before publishing'
        if errors:
            raise ValidationError(errors)

    # ---------- storage ----------

    def _new_cover(self) -> bool:
        return bool(self.cover_image) and not self.cover_image._committed

    def save(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        """Publishing without a go-live time means "now"; a new cover is named after its content and the
        replaced file is removed."""
        if self.status == ContentStatus.PUBLISHED and self.publish_at is None:
            self.publish_at = timezone.now()
        self.read_minutes = ContentItem.estimate_read_minutes(self.body)
        old_name = ''
        if self._new_cover():
            self.cover_image.seek(0)
            data = self.cover_image.read()
            self.cover_image.seek(0)
            extension = sniff_image_extension(data[:16])
            if extension is None:
                raise ValidationError(f'Upload a {ALLOWED_TYPES_TEXT} image')
            self.cover_image.name = f'{sha256_of(data)[:24]}.{extension}'
            if self.pk:
                old_name = ContentItem.objects.filter(pk=self.pk).values_list('cover_image', flat=True).first() or ''
        super().save(*args, **kwargs)
        if old_name and old_name != self.cover_image.name:
            self.cover_image.storage.delete(old_name)


@receiver(post_delete, sender=ContentItem)
def remove_cover_file(sender, instance: ContentItem, **kwargs) -> None:  # noqa: ANN003
    if instance.cover_image:
        instance.cover_image.delete(save=False)
