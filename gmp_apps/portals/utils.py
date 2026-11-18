from typing import Any

from gmp_apps.portals.models import ComplaintPortal


class PortalUtils:
    filter_columns: dict[str, str] = {'categoryId': 'category_id', 'department': 'department'}
    sort_columns: dict[str, str] = {
        'portalId': 'portal_id', 'name': 'name', 'department': 'department', 'categoryName': 'category__name',
        'createdDateTime': 'created_date_time',
    }
    search_columns: list[str] = ['name', 'description', 'department', 'category__name']

    @staticmethod
    def row(portal: ComplaintPortal) -> dict[str, Any]:
        """Member-facing shape: what a member needs to find and visit the portal. No admin fields."""
        return {
            'portalId': portal.portal_id,
            'name': portal.name,
            'description': portal.description,
            'department': portal.department,
            'categoryId': portal.category_id,
            'categoryName': portal.category.name,
            'officialUrl': portal.official_url,
        }
