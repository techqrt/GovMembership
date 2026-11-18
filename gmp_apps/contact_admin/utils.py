from typing import Any

from gmp_apps.contact_admin.models import ContactCategory, ContactRequest


class ContactAdminUtils:
    request_filter_columns: dict[str, str] = {'status': 'status', 'categoryId': 'category_id'}
    request_sort_columns: dict[str, str] = {
        'requestId': 'request_id', 'status': 'status', 'subject': 'subject', 'createdDateTime': 'created_date_time',
    }
    request_search_columns: list[str] = ['subject', 'description']
    category_sort_columns: dict[str, str] = {'categoryId': 'category_id', 'name': 'name'}
    category_search_columns: list[str] = ['name']

    @staticmethod
    def request_row(item: ContactRequest) -> dict[str, Any]:
        """Member-facing shape. The answering admin is deliberately not exposed."""
        return {
            'requestId': item.request_id,
            'categoryId': item.category_id,
            'categoryName': item.category.name,
            'subject': item.subject,
            'description': item.description,
            'status': item.status,
            'adminReply': item.admin_reply,
            'repliedDateTime': item.replied_date_time,
            'createdDateTime': item.created_date_time,
        }

    @staticmethod
    def category_row(category: ContactCategory) -> dict[str, Any]:
        return {'categoryId': category.category_id, 'name': category.name}
