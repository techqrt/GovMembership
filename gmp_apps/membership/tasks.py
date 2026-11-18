import logging

from celery import shared_task

from gmp_apps.membership.models import ReferralInvite

logger = logging.getLogger(__name__)


@shared_task(name='gmp_apps.membership.tasks.expire_referral_invites')
def expire_referral_invites() -> int:
    """Timer job: close open referral invitations past their expiry date.

    Idempotent and cheap. Lazy expiry in the API and admin remains as a safety net, so a missed
    run never lets an expired invitation link a registration.
    """
    expired = ReferralInvite.expire_due()
    logger.info('Expired %s referral invitation(s)', expired)
    return expired
