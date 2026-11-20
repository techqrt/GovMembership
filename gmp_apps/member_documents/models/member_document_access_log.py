from django.conf import settings
from django.db import models


class MemberDocumentAccessLog(models.Model):
    """One row each time an admin downloads a member's document (who, which file, when). Rows are
    kept even if the file or the admin account is later removed."""

    log_id = models.BigAutoField(primary_key=True)
    document_id = models.BigIntegerField()
    document_type = models.CharField(max_length=24)
    member = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='document_access_logs')
    admin = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='document_downloads')
    created_date_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'member_document_access_log'
        ordering = ['-created_date_time']

    def __str__(self) -> str:
        return f'#{self.document_id} read by admin {self.admin_id}'
