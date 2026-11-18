from typing import Any

from django.db.models import Count, Q
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone

from gmp_apps.authentication.models import User
from gmp_apps.contact_admin.models import ContactRequest
from gmp_apps.chatbot.models import KnowledgeEntry
from gmp_apps.content.models import ContentItem
from gmp_apps.portals.models import ComplaintPortal
from gmp.config import Configurations
from gmp_apps.schemes.models import Scheme, SchemeSyncRun
from gmp_apps.membership.models import PermanentApplication, Referral, ReferralInvite


def dashboard_callback(request: HttpRequest, context: dict[str, Any]) -> dict[str, Any]:
    """Plain counts for the admin home page. Each card links to the matching filtered list and is
    shown only to staff who may view that model. No personal data, no charts or analytics."""
    user = request.user
    cards: list[dict[str, Any]] = []

    if user.has_perm('authentication.view_user'):
        counts = User.objects.filter(role='member').aggregate(
            total=Count('pk'),
            general=Count('pk', filter=Q(membership_level='general')),
            active=Count('pk', filter=Q(membership_level='active')),
            permanent=Count('pk', filter=Q(membership_level='permanent')),
            suspended=Count('pk', filter=Q(is_active=False)),
        )
        url = reverse('admin:authentication_user_changelist')
        cards += [
            {'title': 'Members', 'value': counts['total'], 'link': f'{url}?role__exact=member'},
            {'title': 'General', 'value': counts['general'], 'link': f'{url}?membership_level__exact=general'},
            {'title': 'Active', 'value': counts['active'], 'link': f'{url}?membership_level__exact=active'},
            {'title': 'Permanent', 'value': counts['permanent'], 'link': f'{url}?membership_level__exact=permanent'},
            {'title': 'Suspended', 'value': counts['suspended'], 'link': f'{url}?is_active__exact=0'},
        ]
    if user.has_perm('membership.view_permanentapplication'):
        cards.append({
            'title': 'Permanent applications to review',
            'value': PermanentApplication.objects.filter(status='pending').count(),
            'link': reverse('admin:membership_permanentapplication_changelist') + '?status__exact=pending',
        })
    if user.has_perm('membership.view_referral'):
        cards.append({
            'title': 'Flagged referrals to review',
            'value': Referral.objects.filter(status='flagged').count(),
            'link': reverse('admin:membership_referral_changelist') + '?status__exact=flagged',
        })
    if user.has_perm('membership.view_referralinvite'):
        cards.append({
            'title': 'Open referral invitations',
            'value': ReferralInvite.objects.filter(status='invited').count(),
            'link': reverse('admin:membership_referralinvite_changelist') + '?status__exact=invited',
        })
    if user.has_perm('contact_admin.view_contactrequest'):
        cards.append({
            'title': 'Open contact requests',
            'value': ContactRequest.objects.filter(status='open').count(),
            'link': reverse('admin:contact_admin_contactrequest_changelist') + '?status__exact=open',
        })
    if user.has_perm('chatbot.view_knowledgeentry'):
        cards.append({
            'title': 'Approved chatbot entries',
            'value': KnowledgeEntry.objects.filter(status='approved').count(),
            'link': reverse('admin:chatbot_knowledgeentry_changelist') + '?status__exact=approved',
        })
        cards.append({
            'title': 'Chatbot entries awaiting approval',
            'value': KnowledgeEntry.objects.filter(status='draft').count(),
            'link': reverse('admin:chatbot_knowledgeentry_changelist') + '?status__exact=draft',
        })
    if user.has_perm('content.view_contentitem'):
        url = reverse('admin:content_contentitem_changelist')
        cards += [
            {'title': 'Content drafts', 'value': ContentItem.objects.filter(status='draft').count(), 'link': f'{url}?status__exact=draft'},
            {'title': 'Live content', 'value': ContentItem.live().count(), 'link': f'{url}?visibility=live'},
            {
                'title': 'Scheduled content',
                'value': ContentItem.objects.filter(status='published', publish_at__gt=timezone.now()).count(),
                'link': f'{url}?visibility=scheduled',
            },
        ]
    if user.has_perm('portals.view_complaintportal'):
        url = reverse('admin:portals_complaintportal_changelist')
        cards += [
            {'title': 'Active complaint portals', 'value': ComplaintPortal.objects.filter(is_active=True).count(), 'link': f'{url}?is_active__exact=1'},
            {'title': 'Inactive complaint portals', 'value': ComplaintPortal.objects.filter(is_active=False).count(), 'link': f'{url}?is_active__exact=0'},
        ]
    if user.has_perm('schemes.view_scheme'):
        url = reverse('admin:schemes_scheme_changelist')
        cards += [
            {'title': 'Schemes awaiting review', 'value': Scheme.objects.filter(status='pending_review').count(), 'link': f'{url}?status__exact=pending_review'},
            {'title': 'Published schemes', 'value': Scheme.objects.filter(status='published').count(), 'link': f'{url}?status__exact=published'},
        ]
    if user.has_perm('schemes.view_scheme'):
        cards.append({
            'title': 'Schemes waiting for pictures/PDFs',
            'value': Scheme.objects.filter(source_url__isnull=False, is_manual=False, locally_edited=False, media_synced_at__isnull=True).count(),
            'link': reverse('admin:schemes_scheme_changelist') + '?media=pending',
        })
    if user.has_perm('schemes.view_schemesyncrun'):
        cards += sync_cards()
    context['dashboard_cards'] = cards
    return context


def sync_cards() -> list[dict[str, Any]]:
    """Last scheme sync and when the daily schedule should start the next one (about: the schedule
    is an interval from when the scheduler started, not a fixed clock time)."""
    link = reverse('admin:schemes_schemesyncrun_changelist')
    last = SchemeSyncRun.objects.order_by('-started_date_time').first()
    if last is None:
        return [{'title': 'Last scheme sync', 'value': 'Never run', 'link': link}]
    started = timezone.localtime(last.started_date_time)
    next_run = started + timezone.timedelta(hours=Configurations.scheme_sync_interval_hours)
    return [
        {'title': 'Last scheme sync', 'value': f'{last.get_status_display()}, {started:%d %b %H:%M}', 'link': link},
        {'title': 'Next scheme sync (about)', 'value': f'{next_run:%d %b %H:%M}', 'link': link},
    ]
