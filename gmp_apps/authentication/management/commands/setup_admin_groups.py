from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

GROUPS: dict[str, list[tuple[str, str]]] = {
    # Look up members, suspend or reactivate them. Cannot decide referrals or Permanent applications.
    'Member Managers': [
        ('authentication', 'view_user'),
        ('authentication', 'change_user'),
        ('authentication', 'suspend_member'),
    ],
    # Review flagged referrals, Permanent applications and invitations. Cannot suspend members.
    'Membership Reviewers': [
        ('membership', 'view_referral'),
        ('membership', 'change_referral'),
        ('membership', 'view_permanentapplication'),
        ('membership', 'change_permanentapplication'),
        ('membership', 'view_referralinvite'),
        ('membership', 'change_referralinvite'),
    ],
    # Review imported schemes, publish them, edit or add manually, delete, handle the exclusion list, read sync logs.
    'Scheme Reviewers': [
        ('schemes', 'view_scheme'),
        ('schemes', 'add_scheme'),
        ('schemes', 'change_scheme'),
        ('schemes', 'delete_scheme'),
        ('schemes', 'view_schemetag'),
        ('schemes', 'add_schemetag'),
        ('schemes', 'change_schemetag'),
        ('schemes', 'delete_schemetag'),
        ('schemes', 'view_schemeimage'),
        ('schemes', 'add_schemeimage'),
        ('schemes', 'change_schemeimage'),
        ('schemes', 'delete_schemeimage'),
        ('schemes', 'view_schemedocument'),
        ('schemes', 'add_schemedocument'),
        ('schemes', 'change_schemedocument'),
        ('schemes', 'delete_schemedocument'),
        ('schemes', 'publish_scheme'),
        ('schemes', 'view_schemeexclusion'),
        ('schemes', 'delete_schemeexclusion'),
        ('schemes', 'view_schemesyncrun'),
        ('schemes', 'run_scheme_sync'),
    ],
    # Write chatbot knowledge entries as drafts. Cannot approve, retire or delete them, and cannot read chat logs.
    'Knowledge Editors': [
        ('chatbot', 'view_knowledgeentry'),
        ('chatbot', 'add_knowledgeentry'),
        ('chatbot', 'change_knowledgeentry'),
    ],
    # Approve and retire knowledge entries, delete them, and read the chat logs (members type free text).
    'Knowledge Approvers': [
        ('chatbot', 'view_knowledgeentry'),
        ('chatbot', 'add_knowledgeentry'),
        ('chatbot', 'change_knowledgeentry'),
        ('chatbot', 'delete_knowledgeentry'),
        ('chatbot', 'approve_knowledgeentry'),
        ('chatbot', 'view_chatlog'),
    ],
    # Read members' full Aadhaar and PAN numbers (every read is logged). Cannot change members.
    'Identity Reviewers': [
        ('authentication', 'view_user'),
        ('authentication', 'view_government_ids'),
    ],
    # Look at members' uploaded documents and download them (every download is logged). Cannot change or delete anything.
    'Document Reviewers': [
        ('member_documents', 'view_memberdocument'),
        ('member_documents', 'download_memberdocument'),
    ],
    # Decide which dashboard sections members see, in what order and from which level. Nothing else.
    'Dashboard Managers': [
        ('dashboard', 'view_dashboardsection'),
        ('dashboard', 'change_dashboardsection'),
    ],
    # Write and edit content as drafts. Cannot publish, schedule-publish, unpublish, archive or delete.
    'Content Editors': [
        ('content', 'view_contentitem'),
        ('content', 'add_contentitem'),
        ('content', 'change_contentitem'),
        ('content', 'view_contentcategory'),
        ('content', 'add_contentcategory'),
        ('content', 'change_contentcategory'),
    ],
    # Everything editors can do, plus publish/unpublish/archive and delete.
    'Content Publishers': [
        ('content', 'view_contentitem'),
        ('content', 'add_contentitem'),
        ('content', 'change_contentitem'),
        ('content', 'delete_contentitem'),
        ('content', 'publish_contentitem'),
        ('content', 'view_contentcategory'),
        ('content', 'add_contentcategory'),
        ('content', 'change_contentcategory'),
        ('content', 'delete_contentcategory'),
    ],
    # Maintain the complaint-portal directory and its categories. Sees nothing else.
    'Portal Managers': [
        ('portals', 'view_complaintportal'),
        ('portals', 'add_complaintportal'),
        ('portals', 'change_complaintportal'),
        ('portals', 'delete_complaintportal'),
        ('portals', 'view_portalcategory'),
        ('portals', 'add_portalcategory'),
        ('portals', 'change_portalcategory'),
        ('portals', 'delete_portalcategory'),
    ],
    # Answer Contact Admin requests and manage their categories. Cannot see members or decide membership matters.
    'Support Handlers': [
        ('contact_admin', 'view_contactrequest'),
        ('contact_admin', 'change_contactrequest'),
        ('contact_admin', 'view_contactcategory'),
        ('contact_admin', 'add_contactcategory'),
        ('contact_admin', 'change_contactcategory'),
    ],
}


class Command(BaseCommand):
    help = 'Create or refresh the standard admin permission groups (safe to run repeatedly).'

    def handle(self, *args: object, **options: object) -> None:
        for name, wanted in GROUPS.items():
            group, _ = Group.objects.get_or_create(name=name)
            permissions = [Permission.objects.get(content_type__app_label=app, codename=code) for app, code in wanted]
            group.permissions.set(permissions)
            self.stdout.write(f'{name}: {len(permissions)} permissions')
