from typing import Any

from django.urls import reverse

from gmp_apps.member_documents.models import MemberDocument


class MemberDocumentUtils:
    document_filter_columns: dict[str, str] = {'documentType': 'document_type'}
    document_sort_columns: dict[str, str] = {
        'documentId': 'document_id', 'documentType': 'document_type', 'createdDateTime': 'created_date_time', 'sizeBytes': 'size_bytes',
    }
    document_search_columns: list[str] = ['label', 'download_name']

    @staticmethod
    def document_row(item: MemberDocument) -> dict[str, Any]:
        """Owner-facing shape. The stored path, hash and other members' data are never included."""
        return {
            'documentId': item.document_id,
            'documentType': item.document_type,
            'label': item.label,
            'fileName': item.download_name,
            'contentType': item.content_type,
            'sizeBytes': item.size_bytes,
            'createdDateTime': item.created_date_time,
            'downloadUrl': f"{reverse('download_member_documents_document')}?document_id={item.document_id}",
        }
