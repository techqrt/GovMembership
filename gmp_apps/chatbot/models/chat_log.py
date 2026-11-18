from django.conf import settings
from django.db import models


class ChatOutcome(models.TextChoices):
    ANSWERED = 'answered', 'Answered from the knowledge base'
    NO_ANSWER = 'no_answer', 'No approved answer'
    UNAVAILABLE = 'unavailable', 'Provider unavailable'


class ChatLog(models.Model):
    """Audit record of a question and what the assistant replied. Kept for a limited time
    (CHATBOT_LOG_RETENTION_DAYS) so admins can see which questions the knowledge base misses."""

    log_id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_logs')
    question = models.CharField(max_length=1000)
    language = models.CharField(max_length=16, blank=True, default='')
    outcome = models.CharField(max_length=16, choices=ChatOutcome.choices)
    reason = models.CharField(max_length=120, blank=True, default='')   # internal: why there was no answer
    entry_ids = models.JSONField(default=list, blank=True)
    reply = models.TextField(blank=True, default='')
    created_date_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'chat_log'
        ordering = ['-created_date_time', '-log_id']
        indexes = [models.Index(fields=['user', 'created_date_time']), models.Index(fields=['outcome', 'created_date_time'])]

    def __str__(self) -> str:
        return f'{self.outcome}: {self.question[:40]}'
