from datetime import timedelta

from django.db import models
from django.utils import timezone

# A run that has been "running" longer than this is treated as dead (crashed worker) and replaced.
STALE_AFTER = timedelta(hours=3)


class SyncStatus(models.TextChoices):
    RUNNING = 'running', 'Running'
    SUCCESS = 'success', 'Success'
    PARTIAL = 'partial', 'Finished with errors'
    FAILED = 'failed', 'Failed'


class SchemeSyncRun(models.Model):
    run_id = models.BigAutoField(primary_key=True)
    trigger = models.CharField(max_length=16, default='beat')  # beat | command
    status = models.CharField(max_length=16, choices=SyncStatus.choices, default=SyncStatus.RUNNING)
    started_date_time = models.DateTimeField(auto_now_add=True)
    finished_date_time = models.DateTimeField(null=True, blank=True)
    sitemap_urls = models.PositiveIntegerField(default=0)
    scheme_urls = models.PositiveIntegerField(default=0)
    fetched = models.PositiveIntegerField(default=0)
    images_downloaded = models.PositiveIntegerField(default=0)
    documents_downloaded = models.PositiveIntegerField(default=0)
    media_pending = models.PositiveIntegerField(default=0)  # source schemes still waiting for their pictures/PDFs after this run
    created = models.PositiveIntegerField(default=0)
    updated = models.PositiveIntegerField(default=0)
    unchanged = models.PositiveIntegerField(default=0)
    skipped_excluded = models.PositiveIntegerField(default=0)
    skipped_edited = models.PositiveIntegerField(default=0)
    skipped_invalid = models.PositiveIntegerField(default=0)
    errors = models.PositiveIntegerField(default=0)
    error_summary = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'scheme_sync_run'
        ordering = ['-started_date_time']
        permissions = [('run_scheme_sync', 'Can start a scheme sync from the admin')]

    def __str__(self) -> str:
        return f'Sync #{self.run_id} {self.status}'

    @staticmethod
    def is_busy() -> bool:
        """Another run is in progress (and not stale), so a second one must not start."""
        cutoff = timezone.now() - STALE_AFTER
        return SchemeSyncRun.objects.filter(status=SyncStatus.RUNNING, started_date_time__gte=cutoff).exists()
