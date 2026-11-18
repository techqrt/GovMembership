from django.db import models


class ContactCategory(models.Model):
    """Subject area of a Contact Admin request. Managed by admins; inactive ones are hidden from new requests."""

    category_id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=80, unique=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_date_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'contact_category'
        ordering = ['sort_order', 'name']
        verbose_name_plural = 'contact categories'

    def __str__(self) -> str:
        return self.name
