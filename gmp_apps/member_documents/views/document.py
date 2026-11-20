from django.http import HttpResponse
from rest_framework.response import Response

from gmp.constants import Constants
from gmp_apps.authentication.models import User
from gmp_apps.common.common import Common
from gmp_apps.common.dataclasses.request.get_all import GetAll
from gmp_apps.common.exceptions.errors import NotFoundError
from gmp_apps.common.query import GetAllQuery
from gmp_apps.common.utils import Utils
from gmp_apps.contact_admin.models.contact_request import OPEN_STATUSES
from gmp_apps.member_documents.dataclasses.request.create.create_document import CreateDocumentRequest
from gmp_apps.member_documents.dataclasses.request.get.get_document import GetDocumentRequest
from gmp_apps.member_documents.files import attachment_response
from gmp_apps.member_documents.models import MemberDocument
from gmp_apps.member_documents.utils import MemberDocumentUtils


class MemberDocumentView:
    def __init__(self) -> None:
        self.data_create = 'Your document was uploaded'
        self.data_get = 'Data fetched successfully'
        self.data_delete = 'Your document was deleted'

    @staticmethod
    def _own(document_id: int, user_id: int) -> MemberDocument:
        # Filtering by the caller makes another member's id look like a missing one (IDOR).
        document = MemberDocument.objects.filter(document_id=document_id, user_id=user_id).first()
        if document is None:
            raise NotFoundError(Constants.not_found_item)
        return document

    @Common().exception_handler
    def create_extract(self, params: CreateDocumentRequest) -> Response:
        """The owner is always the caller (from the token): there is no way to upload for someone else."""
        user = User.objects.get(user_id=params.user_id)
        document = MemberDocument.add(user=user, document_type=params.document_type, upload=params.file, label=params.label)
        return Response(Utils.success_response_data(message=self.data_create, data=MemberDocumentUtils.document_row(document)))

    @Common().exception_handler
    def get_extract(self, params: GetDocumentRequest) -> Response:
        document = self._own(params.document_id, params.user_id)
        return Response(Utils.success_response_data(message=self.data_get, data=MemberDocumentUtils.document_row(document)))

    @Common().exception_handler
    def get_all_extract(self, params: GetAll) -> Response:
        queryset = MemberDocument.objects.filter(user_id=params.user_id)
        queryset = GetAllQuery.apply(
            queryset, params,
            sort_columns=MemberDocumentUtils.document_sort_columns,
            filter_columns=MemberDocumentUtils.document_filter_columns,
            search_columns=MemberDocumentUtils.document_search_columns,
            default_ordering='-created_date_time',
        )
        rows, total_page = Utils.paginate_queryset(queryset, params.page_num, params.limit)
        data = GetAllQuery.select_values([MemberDocumentUtils.document_row(r) for r in rows], params)
        page = Utils.add_page_parameter(final_data=data, page_num=params.page_num, total_page=total_page, present_url=params.present_url)
        return Response(Utils.success_response_data(message=self.data_get, data=page))

    @Common().exception_handler
    def delete_extract(self, params: GetDocumentRequest) -> Response:
        document = self._own(params.document_id, params.user_id)
        if document.permanent_applications.filter(status='pending').exists():
            raise ValueError(Constants.document_in_review)
        if document.contact_requests.filter(status__in=OPEN_STATUSES).exists():
            raise ValueError(Constants.document_in_request)
        document.delete()  # the post_delete hook removes the stored file
        return Response(Utils.success_response_data(message=self.data_delete))

    @Common().exception_handler
    def download_extract(self, params: GetDocumentRequest) -> HttpResponse:
        document = self._own(params.document_id, params.user_id)
        return attachment_response(document.file.open('rb'), document.download_name)
