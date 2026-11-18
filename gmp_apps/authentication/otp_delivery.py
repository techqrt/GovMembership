import logging

logger = logging.getLogger(__name__)


class ConsoleOtpBackend:
    """Development backend: logs the OTP. Replace with an SMS/email provider backend.

    Provider availability and cost are outside this project's scope, so delivery
    sits behind the OTP_DELIVERY_BACKEND setting.
    """

    @staticmethod
    def send(channel: str, destination: str, code: str, purpose: str) -> None:
        logger.warning('OTP (%s) for %s via %s: %s', purpose, destination, channel, code)


class LocMemOtpBackend:
    """Test backend: keeps sent messages in `outbox`."""

    outbox: list[dict[str, str]] = []

    @staticmethod
    def send(channel: str, destination: str, code: str, purpose: str) -> None:
        LocMemOtpBackend.outbox.append(
            {'channel': channel, 'destination': destination, 'code': code, 'purpose': purpose}
        )
