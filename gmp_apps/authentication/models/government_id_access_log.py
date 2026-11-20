from django.conf import settings
from django.db import models


class GovernmentIdAccessLog(models.Model):
    """One row each time an admin reads a member's full Aadhaar or PAN, or searches by a full number.
    Kept even if the admin account is later removed."""

    log_id = models.BigAutoField(primary_key=True)
    admin = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='government_id_reads')
    member = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='government_id_accesses')
    action = models.CharField(max_length=16)   # reveal_aadhaar | reveal_pan | search_aadhaar | search_pan
    created_date_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'government_id_access_log'
        ordering = ['-created_date_time']

    def __str__(self) -> str:
        return f'{self.action} by admin {self.admin_id}'
