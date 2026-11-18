"""One builder per dashboard section. Each reads only the caller's own data or content the caller may
read, takes a handful of latest items plus a total, and never exposes another member's details."""
from collections.abc import Callable
from typing import Any

from django.db.models import Count

from gmp.config import Configurations
from gmp_apps.chatbot.service import is_available
from gmp_apps.authentication.models import User
from gmp_apps.common.utils import Utils
from gmp_apps.contact_admin.models import ContactRequest
from gmp_apps.contact_admin.models.contact_request import OPEN_STATUSES
from gmp_apps.content.models import ContentItem
from gmp_apps.content.models.content_item import ContentType
from gmp_apps.content.utils import ContentUtils
from gmp_apps.membership.utils import MembershipUtils
from gmp_apps.notifications.models import Notification
from gmp_apps.notifications.utils import NotificationUtils
from gmp_apps.portals.models import ComplaintPortal
from gmp_apps.portals.utils import PortalUtils
from gmp_apps.portals.views.portal import visible_portals
from gmp_apps.schemes.models import Scheme
from gmp_apps.schemes.models.scheme import SchemeStatus
from gmp_apps.schemes.utils import SchemeUtils
from gmp_apps.schemes.views.scheme import LIST_DEFERRED


class DashboardContext:
    """What every builder needs, with the shared per-request lookups done at most once."""

    def __init__(self, user: User, request_url: str) -> None:
        self.user = user
        self.base = Utils.public_base_url(request_url)
        self.limit = Configurations.dashboard_items_per_section
        self._content_counts: dict[str, int] | None = None

    def content_counts(self) -> dict[str, int]:
        if self._content_counts is None:
            visible = ContentItem.visible_for(self.user.membership_level)
            self._content_counts = dict(visible.values_list('content_type').annotate(total=Count('content_id')).order_by())
        return self._content_counts


def profile(context: DashboardContext) -> dict[str, Any]:
    user = context.user
    return {
        'membershipId': user.membership_id, 'fullName': user.full_name, 'email': user.email, 'mobileNumber': user.mobile_number,
        'emailVerified': user.email_verified, 'mobileVerified': user.mobile_verified, 'membershipLevel': user.membership_level,
        'memberSince': user.created_date_time,
    }


def membership(context: DashboardContext) -> dict[str, Any]:
    return MembershipUtils.progress_data(context.user)


def content_section(content_type: str) -> Callable[[DashboardContext], dict[str, Any]]:
    def build(context: DashboardContext) -> dict[str, Any]:
        items = (
            ContentItem.visible_for(context.user.membership_level).filter(content_type=content_type)
            .select_related('category').defer('body').order_by('-is_pinned', '-publish_at')[:context.limit]
        )
        return {'total': context.content_counts().get(content_type, 0), 'items': [ContentUtils.row(i, context.base) for i in items]}

    return build


def schemes(context: DashboardContext) -> dict[str, Any]:
    published = Scheme.objects.filter(status=SchemeStatus.PUBLISHED)
    latest = published.defer(*LIST_DEFERRED).prefetch_related('tags', 'images').order_by('-updated_date_time', '-pk')[:context.limit]
    return {'total': published.count(), 'items': [SchemeUtils.list_row(s, context.base) for s in latest]}


def portals(context: DashboardContext) -> dict[str, Any]:
    visible = visible_portals()
    first = visible.order_by('category__sort_order', 'category__name', 'sort_order', 'name')[:context.limit]
    return {'total': ComplaintPortal.objects.filter(is_active=True, category__is_active=True).count(), 'items': [PortalUtils.row(p) for p in first]}


def support(context: DashboardContext) -> dict[str, Any]:
    own = ContactRequest.objects.filter(user_id=context.user.user_id)
    latest = own.select_related('category').order_by('-created_date_time', '-pk')[:Configurations.dashboard_support_items]
    return {
        'openRequests': own.filter(status__in=OPEN_STATUSES).count(),
        'latest': [
            {
                'requestId': r.request_id, 'subject': r.subject, 'categoryName': r.category.name, 'status': r.status,
                'hasReply': bool(r.admin_reply), 'repliedDateTime': r.replied_date_time, 'createdDateTime': r.created_date_time,
            }
            for r in latest
        ],
    }


def notifications(context: DashboardContext) -> dict[str, Any]:
    latest = Notification.objects.filter(user_id=context.user.user_id)[:context.limit]
    return {'unreadCount': Notification.unread_count(context.user.user_id), 'latest': [NotificationUtils.row(n) for n in latest]}


def chatbot(context: DashboardContext) -> dict[str, Any]:
    """Entry point to the chatbot. It stays unavailable until the chatbot feature exists and is switched on."""
    return {'available': is_available()}


BUILDERS: dict[str, Callable[[DashboardContext], dict[str, Any]]] = {
    'profile': profile,
    'membership': membership,
    'announcements': content_section(ContentType.ANNOUNCEMENT),
    'posts': content_section(ContentType.POST),
    'videos': content_section(ContentType.VIDEO),
    'tutorials': content_section(ContentType.TUTORIAL),
    'org_updates': content_section(ContentType.ORG_UPDATE),
    'schemes': schemes,
    'portals': portals,
    'support': support,
    'notifications': notifications,
    'chatbot': chatbot,
}
