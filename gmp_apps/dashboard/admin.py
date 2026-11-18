from django.contrib import admin
from django.http import HttpRequest
from unfold.admin import ModelAdmin

from gmp_apps.dashboard.models import DashboardSection
from gmp_apps.dashboard.models.dashboard_section import LOCKED_SECTIONS


@admin.register(DashboardSection)
class DashboardSectionAdmin(ModelAdmin):
    """Which sections members see on their dashboard, in what order, and from which membership level.
    Profile and Membership are fixed on for everyone. Sections cannot be added or deleted here."""

    list_display = ('title', 'key', 'is_enabled', 'min_level', 'sort_order', 'locked')
    list_editable = ('is_enabled', 'min_level', 'sort_order')
    list_filter = ('is_enabled', 'min_level')
    ordering = ('sort_order', 'section_id')

    @admin.display(description='Fixed on', boolean=True)
    def locked(self, obj: DashboardSection) -> bool:
        return obj.key in LOCKED_SECTIONS

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: DashboardSection | None = None) -> bool:
        return False
