import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from gmp.config import Configurations
from gmp_apps.chatbot.models import ChatLog

logger = logging.getLogger(__name__)


def purge_old_logs() -> int:
    cutoff = timezone.now() - timedelta(days=Configurations.chatbot_log_retention_days)
    deleted, _ = ChatLog.objects.filter(created_date_time__lt=cutoff).delete()
    return deleted


@shared_task(name='gmp_apps.chatbot.tasks.purge_chat_logs')
def purge_chat_logs() -> int:
    """Daily: delete chat logs older than CHATBOT_LOG_RETENTION_DAYS (members type free text, so keep it short-lived)."""
    deleted = purge_old_logs()
    logger.info('Purged %s chat log(s)', deleted)
    return deleted
