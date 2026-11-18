from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import QuerySet

from gmp_apps.chatbot.validators import validate_links, validate_screens


class EntryStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    APPROVED = 'approved', 'Approved'
    RETIRED = 'retired', 'Retired'


class KnowledgeEntry(models.Model):
    """One approved question and answer the chatbot may use. The chatbot answers ONLY from approved
    entries: nothing else (no web, no other platform data) is ever put in front of the model."""

    entry_id = models.BigAutoField(primary_key=True)
    question = models.CharField(max_length=300)
    answer = models.TextField(max_length=2000)
    language = models.CharField(max_length=8, default='en')   # language the answer is written in (ISO 639-1)
    category = models.CharField(max_length=80, blank=True, default='')
    links = models.JSONField(default=list, blank=True, validators=[validate_links])      # curated: [{label, url}]
    screens = models.JSONField(default=list, blank=True, validators=[validate_screens])  # app navigation shortcuts
    status = models.CharField(max_length=16, choices=EntryStatus.choices, default=EntryStatus.DRAFT)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='knowledge_created')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='knowledge_approved')
    approved_date_time = models.DateTimeField(null=True, blank=True)
    created_date_time = models.DateTimeField(auto_now_add=True)
    updated_date_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'knowledge_entry'
        ordering = ['sort_order', 'entry_id']
        verbose_name_plural = 'knowledge entries'
        permissions = [('approve_knowledgeentry', 'Can approve or retire knowledge entries')]

    def __str__(self) -> str:
        return self.question

    @staticmethod
    def approved() -> QuerySet:
        return KnowledgeEntry.objects.filter(status=EntryStatus.APPROVED)

    def clean(self) -> None:
        if not self.question.strip() or not self.answer.strip():
            raise ValidationError('A question and an answer are both required')
        if not self.language.isalpha() or not 2 <= len(self.language) <= 3:
            raise ValidationError({'language': 'Use a 2 or 3 letter language code, for example en or hi'})
        self.language = self.language.lower()
