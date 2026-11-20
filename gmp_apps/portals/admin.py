from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.decorators import action, display

from gmp_apps.portals.models import ComplaintPortal, PortalCategory


@admin.register(ComplaintPortal)
class ComplaintPortalAdmin(ModelAdmin):
    """The directory: add, edit, activate/deactivate and delete portals. Members only see active portals
    of active categories. Links are validated on every save (http/https, no credentials, no private addresses)."""

    list_display = ('name', 'department', 'category', 'visit', 'is_active', 'sort_order', 'updated_date_time')
    list_filter = ('is_active', 'category')
    search_fields = ('name', 'description', 'department', 'official_url', 'file_complaint_url', 'track_status_url', 'category__name')
    list_select_related = ('category',)
    ordering = ('category__sort_order', 'category__name', 'sort_order', 'name')
    fields = ('name', 'category', 'department', 'description', 'official_url', 'file_complaint_url', 'track_status_url', 'sort_order', 'is_active')
    actions = ['activate_portals', 'deactivate_portals']

    @display(description='Official URL')
    def visit(self, obj: ComplaintPortal) -> str:
        return format_html('<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>', obj.official_url, obj.official_url[:60])

    @action(description='Activate selected portals (visible to members)', permissions=['change'])
    def activate_portals(self, request: HttpRequest, queryset: QuerySet) -> None:
        count = queryset.filter(is_active=False).update(is_active=True)
        self.message_user(request, f'{count} portal(s) activated.')

    @action(description='Deactivate selected portals (hidden from members)', permissions=['change'])
    def deactivate_portals(self, request: HttpRequest, queryset: QuerySet) -> None:
        count = queryset.filter(is_active=True).update(is_active=False)
        self.message_user(request, f'{count} portal(s) deactivated.')


@admin.register(PortalCategory)
class PortalCategoryAdmin(ModelAdmin):
    """Portal categories. Deactivating a category hides all its portals from members. A category that still
    has portals cannot be deleted: deactivate it, or move/delete its portals first."""

    list_display = ('name', 'sort_order', 'is_active', 'portal_count')
    list_editable = ('sort_order', 'is_active')
    search_fields = ('name',)

    @display(description='Portals')
    def portal_count(self, obj: PortalCategory) -> int:
        return obj.portals.count()
