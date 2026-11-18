from django.core.management.base import BaseCommand

from gmp_apps.chatbot.tasks import purge_old_logs


class Command(BaseCommand):
    help = 'Delete chat logs older than CHATBOT_LOG_RETENTION_DAYS.'

    def handle(self, *args: object, **options: object) -> None:
        self.stdout.write(f'Deleted {purge_old_logs()} chat log(s).')
