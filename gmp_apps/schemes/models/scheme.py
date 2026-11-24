from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from gmp_apps.authentication.models import User
from gmp_apps.schemes.classification import NATIONAL, STATE, STATE_CHOICES


class SchemeStatus(models.TextChoices):
    PENDING_REVIEW = 'pending_review', 'Pending review'  # imported or added, not visible to members
    PUBLISHED = 'published', 'Published'                  # visible to members
    UNPUBLISHED = 'unpublished', 'Unpublished'            # hidden again by an admin


class SchemeLevel(models.TextChoices):
    NATIONAL = NATIONAL, 'National'
    STATE = STATE, 'State'


class Scheme(models.Model):
    """A government initiative. Imported records are identified by their source URL; manual
    records may have none. Members only ever see published schemes."""

    scheme_id = models.BigAutoField(primary_key=True)
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True, default='')
    eligibility = models.TextField(blank=True, default='')
    benefits = models.TextField(blank=True, default='')
    application_procedure = models.TextField(blank=True, default='')
    required_documents = models.TextField(blank=True, default='')
    department = models.CharField(max_length=200, blank=True, default='')
    highlights = models.TextField(blank=True, default='')
    contact_details = models.TextField(blank=True, default='')
    # [{kind: website|brochure|link, label, url}] http(s) only, validated at parse and admin time
    links = models.JSONField(default=list, blank=True)
    # [{label, value}] rows of the page's overview table
    overview = models.JSONField(default=list, blank=True)
    # [{heading, text}] every section that is not one of the five core fields, in page order
    additional_sections = models.JSONField(default=list, blank=True)
    source_url = models.URLField(max_length=500, unique=True, null=True, blank=True)
    status = models.CharField(max_length=16, choices=SchemeStatus.choices, default=SchemeStatus.PENDING_REVIEW)
    is_accepting_applications = models.BooleanField(
        default=True, help_text='Shown to members as Active or Closed. Set by an admin; the sync never changes it.',
    )
    # National or state. Empty means "not set yet": such a scheme is still listed, it just matches neither filter.
    # Filled by the sync only while empty (see classification.py), editable by an admin, never overwritten once set.
    level = models.CharField(max_length=8, choices=SchemeLevel.choices, blank=True, default='')
    state = models.CharField(max_length=60, choices=STATE_CHOICES, blank=True, default='')
    is_manual = models.BooleanField(default=False)
    # True once an admin edits an imported scheme: the sync then leaves its content alone.
    locally_edited = models.BooleanField(default=False)
    content_hash = models.CharField(max_length=64, blank=True, default='')
    source_lastmod = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    # When this scheme's pictures and PDFs were last brought fully up to date with its page. NULL means
    # "not verified yet" (imported by an older version, or a download failed): the sync re-queues it.
    media_synced_at = models.DateTimeField(null=True, blank=True)
    # What the page promised at that time: {'images': [source URLs], 'documents': [source URLs]}.
    # Internal: lets us verify the stored media without fetching the page. Never returned to clients.
    expected_media = models.JSONField(default=dict, blank=True)
    published_date_time = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='schemes_reviewed',
    )
    created_date_time = models.DateTimeField(auto_now_add=True)
    updated_date_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'scheme'
        permissions = [('publish_scheme', 'Can publish or unpublish schemes')]
        indexes = [models.Index(fields=['status', 'department'])]

    def __str__(self) -> str:
        return self.title

    def clean(self) -> None:
        super().clean()
        if self.level == SchemeLevel.STATE and not self.state:
            raise ValidationError({'state': 'Choose the state for a state scheme.'})
        if self.level != SchemeLevel.STATE and self.state:
            raise ValidationError({'state': 'A state can only be set on a state scheme.'})

    def set_status(self, status: str, admin: User) -> None:
        self.status = status
        self.reviewed_by = admin
        if status == SchemeStatus.PUBLISHED and self.published_date_time is None:
            self.published_date_time = timezone.now()
        self.save(update_fields=['status', 'reviewed_by', 'published_date_time', 'updated_date_time'])

    def set_tags(self, tags: list[dict[str, str]]) -> bool:
        """Replace this scheme's tags with `tags` ([{group, name}]). Returns True if anything changed."""
        from gmp_apps.schemes.models.scheme_tag import SchemeTag

        wanted = {(t['group'], t['name']) for t in tags}
        current = set(self.tags.values_list('group', 'name'))
        if wanted == current:
            return False
        for group, name in current - wanted:
            self.tags.filter(group=group, name=name).delete()
        for group, name in wanted - current:
            SchemeTag.objects.create(scheme=self, group=group, name=name)
        return True

    @staticmethod
    def remove(scheme_id: int, admin: User, reason: str = '') -> None:
        """Delete the local record only. Nothing on the source site is touched.

        An imported scheme's URL goes onto the exclusion list so the next sync does not bring it
        straight back; removing the entry from that list allows a re-import.
        """
        from gmp_apps.schemes.models.scheme_exclusion import SchemeExclusion

        with transaction.atomic():
            scheme = Scheme.objects.select_for_update().get(pk=scheme_id)
            if scheme.source_url:
                SchemeExclusion.objects.get_or_create(
                    source_url=scheme.source_url,
                    defaults={'excluded_by': admin, 'reason': reason[:255] or f'Deleted: {scheme.title}'[:255]},
                )
            scheme.delete()
