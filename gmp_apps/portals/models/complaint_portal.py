from django.core.exceptions import ValidationError
from django.db import models

from gmp_apps.portals.models.portal_category import PortalCategory
from gmp_apps.portals.validators import url_key, validate_portal_url


class ComplaintPortal(models.Model):
    """An official government grievance portal members can visit. This platform only lists portals:
    it never registers, tracks or resolves a complaint."""

    portal_id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=200)
    description = models.TextField(max_length=2000, blank=True, default='')
    department = models.CharField(max_length=200, blank=True, default='')
    official_url = models.CharField(max_length=500, validators=[validate_portal_url])
    url_key = models.CharField(max_length=520, unique=True, editable=False)
    category = models.ForeignKey(PortalCategory, on_delete=models.PROTECT, related_name='portals')
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_date_time = models.DateTimeField(auto_now_add=True)
    updated_date_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'complaint_portal'
        ordering = ['sort_order', 'name']
        indexes = [models.Index(fields=['is_active', 'category'])]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        self.official_url = (self.official_url or '').strip()
        if not self.official_url:
            return
        validate_portal_url(self.official_url)
        key = url_key(self.official_url)
        if ComplaintPortal.objects.filter(url_key=key).exclude(pk=self.pk).exists():
            raise ValidationError({'official_url': 'A portal with this URL is already listed'})

    def save(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        """Validate on every save (not only through forms), so no code path can store an unsafe link."""
        self.official_url = (self.official_url or '').strip()
        validate_portal_url(self.official_url)
        self.url_key = url_key(self.official_url)
        super().save(*args, **kwargs)
