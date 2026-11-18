from django.db import models


class ContentCategory(models.Model):
    """Topic group for content (admin-managed). Deactivating one hides all its content from members."""

    category_id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=80, unique=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_date_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'content_category'
        ordering = ['sort_order', 'name']
        verbose_name_plural = 'content categories'

    def __str__(self) -> str:
        return self.name
