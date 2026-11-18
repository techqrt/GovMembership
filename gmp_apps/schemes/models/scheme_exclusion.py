from django.conf import settings
from django.db import models


class SchemeExclusion(models.Model):
    """Source URLs an admin deleted. The sync skips them until the entry is removed here."""

    exclusion_id = models.BigAutoField(primary_key=True)
    source_url = models.URLField(max_length=500, unique=True)
    reason = models.CharField(max_length=255, blank=True, default='')
    excluded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='scheme_exclusions',
    )
    created_date_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'scheme_exclusion'

    def __str__(self) -> str:
        return self.source_url
