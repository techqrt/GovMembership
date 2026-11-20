from django.contrib import admin
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.urls import path, reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from gmp_apps.member_documents.files import attachment_response
from gmp_apps.member_documents.models import MemberDocument, MemberDocumentAccessLog


@admin.register(MemberDocument)
class MemberDocumentAdmin(ModelAdmin):
    """Members' uploaded documents. Read-only: staff with the download permission can fetch a file;
    each download is written to the access log. Members delete their own files through the API."""

    list_display = ('document_id', 'member', 'document_type', 'label', 'download_name', 'size_bytes', 'created_date_time', 'download_link')
    list_filter = ('document_type', 'content_type')
    search_fields = ('user__membership_id', 'user__full_name', 'label', 'download_name')
    list_select_related = ('user',)
    ordering = ('-created_date_time',)
    readonly_fields = ('user', 'document_type', 'label', 'download_name', 'content_type', 'size_bytes', 'sha256', 'created_date_time', 'download_link')
    fields = readonly_fields

    @admin.display(description='Member', ordering='user__membership_id')
    def member(self, obj: MemberDocument) -> str:
        return f'{obj.user.membership_id} ({obj.user.full_name})'

    @admin.display(description='File')
    def download_link(self, obj: MemberDocument) -> str:
        if not obj.pk:
            return '-'
        return format_html('<a href="{}">Download</a>', reverse('admin:member_documents_memberdocument_download', args=[obj.pk]))

    def get_urls(self) -> list:
        extra = [path('<int:object_id>/download/', self.admin_site.admin_view(self.download_view), name='member_documents_memberdocument_download')]
        return extra + super().get_urls()

    def download_view(self, request: HttpRequest, object_id: int) -> HttpResponse:
        """Needs the download permission; the read is logged before the file is sent."""
        if not self.has_download_permission(request):
            return HttpResponse('You do not have permission to download documents.', status=403)
        document = MemberDocument.objects.select_related('user').filter(pk=object_id).first()
        if document is None or not document.file or not document.file.storage.exists(document.file.name):
            raise Http404('No such document')
        MemberDocumentAccessLog.objects.create(
            document_id=document.pk, document_type=document.document_type, member=document.user, admin=request.user,
        )
        response: FileResponse = attachment_response(document.file.open('rb'), document.download_name)
        return response

    def has_download_permission(self, request: HttpRequest) -> bool:
        return request.user.has_perm('member_documents.download_memberdocument')

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: MemberDocument | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: MemberDocument | None = None) -> bool:
        return False


@admin.register(MemberDocumentAccessLog)
class MemberDocumentAccessLogAdmin(ModelAdmin):
    """Who downloaded which member document, and when. Read-only audit trail."""

    list_display = ('log_id', 'created_date_time', 'admin', 'member', 'document_type', 'document_id')
    list_filter = ('document_type',)
    search_fields = ('admin__membership_id', 'member__membership_id')
    list_select_related = ('admin', 'member')

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: MemberDocumentAccessLog | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: MemberDocumentAccessLog | None = None) -> bool:
        return False
