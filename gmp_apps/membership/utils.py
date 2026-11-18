from typing import Any

from gmp.config import Configurations
from gmp_apps.membership.models import PermanentApplication, Referral
from gmp_apps.membership.models.referral import ReferralStatus


class MembershipUtils:
    # snake_case column -> camelCase response key
    application_mapper: dict[str, str] = {
        'application_id': 'applicationId',
        'reason': 'reason',
        'status': 'status',
        'admin_remarks': 'adminRemarks',
        'created_date_time': 'createdDateTime',
        'reviewed_date_time': 'reviewedDateTime',
    }
    application_filter_columns: dict[str, str] = {'status': 'status'}
    application_sort_columns: dict[str, str] = {
        'applicationId': 'application_id', 'status': 'status', 'createdDateTime': 'created_date_time',
    }
    referral_filter_columns: dict[str, str] = {'status': 'status'}
    referral_sort_columns: dict[str, str] = {
        'referralId': 'referral_id', 'status': 'status', 'createdDateTime': 'created_date_time',
    }
    # ---------- referral ----------

    @staticmethod
    def member_referral_status(status: str) -> str:
        """Members never see the word 'flagged': fraud rules stay opaque."""
        return 'under_review' if status == ReferralStatus.FLAGGED else status

    @staticmethod
    def member_referral_row(referral: Referral) -> dict[str, Any]:
        return {
            'referralId': referral.referral_id,
            'referredFirstName': referral.referred.full_name.split(' ')[0],
            'status': MembershipUtils.member_referral_status(referral.status),
            'createdDateTime': referral.created_date_time,
            'verifiedDateTime': referral.verified_date_time,
        }

    # ---------- referral invite ----------

    invite_filter_columns: dict[str, str] = {'status': 'status'}
    invite_sort_columns: dict[str, str] = {
        'inviteId': 'invite_id', 'fullName': 'full_name', 'status': 'status', 'createdDateTime': 'created_date_time',
        'expiresAt': 'expires_at',
    }
    invite_search_columns: list[str] = ['full_name', 'email', 'mobile_number']

    @staticmethod
    def invite_row(invite: Any, referral_code: str) -> dict[str, Any]:
        return {
            'inviteId': invite.invite_id,
            'fullName': invite.full_name,
            'email': invite.email,
            'mobileNumber': invite.mobile_number,
            'status': invite.status,
            'expiresAt': invite.expires_at,
            'referralLink': MembershipUtils.referral_link(referral_code),
            'createdDateTime': invite.created_date_time,
        }

    # ---------- permanent application ----------

    @staticmethod
    def application_row(application: PermanentApplication) -> dict[str, Any]:
        return {
            camel: getattr(application, column) for column, camel in MembershipUtils.application_mapper.items()
        }

    # ---------- progress ----------

    @staticmethod
    def progress_data(user: Any) -> dict[str, Any]:
        """The member's level, referral code/link, referral progress and Permanent application state.
        Shared by the progress endpoint and the dashboard."""
        required = Configurations.active_referrals_required
        verified = Referral.verified_count(user.user_id)
        pending = Referral.objects.filter(referrer=user, status__in=[ReferralStatus.PENDING, ReferralStatus.FLAGGED]).count()
        latest = PermanentApplication.objects.filter(user=user).order_by('-created_date_time', '-pk').first()
        has_open = PermanentApplication.objects.filter(user=user, status='pending').exists()
        return {
            'membershipLevel': user.membership_level,
            'referralCode': user.referral_code,
            'referralLink': MembershipUtils.referral_link(user.referral_code),
            'verifiedReferrals': verified,
            'pendingReferrals': pending,
            'requiredReferrals': required,
            'remainingReferrals': max(required - verified, 0),
            'canApplyForPermanent': user.membership_level == 'active' and not has_open,
            'permanentApplication': {'applicationId': latest.application_id, 'status': latest.status} if latest else None,
        }

    @staticmethod
    def referral_link(referral_code: str) -> str:
        return f'{Configurations.referral_link_base_url}?ref={referral_code}'
