import json

from django.core.management.base import BaseCommand, CommandError

from gmp_apps.authentication.models import User
from gmp_apps.chatbot.service import ChatbotService
from gmp_apps.common.exceptions.errors import ServiceUnavailableError, TooManyRequestsError


class Command(BaseCommand):
    help = (
        'Ask the chatbot one question from the command line to verify the real AI provider end to end '
        '(needs CHATBOT_ENABLED=True, GEMINI_API_KEY and at least one approved knowledge entry). '
        'The question is logged against the given member like any other.'
    )

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument('question')
        parser.add_argument('--member', required=True, help='Membership ID of the member to ask as (for the audit log)')

    def handle(self, *args: object, **options: object) -> None:
        member = User.objects.filter(membership_id=str(options['member']).upper(), role='member').first()
        if member is None:
            raise CommandError('No member with that membership ID')
        try:
            result = ChatbotService().ask(member.user_id, str(options['question']))
        except (ValueError, ServiceUnavailableError, TooManyRequestsError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(json.dumps(result, indent=2, ensure_ascii=False))
