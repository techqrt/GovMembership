from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from django.db.models import QuerySet
from django.http import HttpRequest
from unfold.admin import ModelAdmin

from gmp_apps.app_text.models import AppText


class MissingHindiFilter(SimpleListFilter):
    title = 'Hindi text'
    parameter_name = 'hindi'

    def lookups(self, request: HttpRequest, model_admin: admin.ModelAdmin) -> list[tuple[str, str]]:
        return [('missing', 'Missing (shows English)'), ('done', 'Written')]

    def queryset(self, request: HttpRequest, queryset: QuerySet[AppText]) -> QuerySet[AppText]:
        if self.value() == 'missing':
            return queryset.filter(text_hi='')
        if self.value() == 'done':
            return queryset.exclude(text_hi='')
        return queryset


@admin.register(AppText)
class AppTextAdmin(ModelAdmin):
    """The wording the app shows, in English and Hindi. The app fetches it from /app_text/get_all/."""

    list_display = ('key', 'text_en', 'text_hi', 'is_active', 'updated_date_time')
    list_filter = ('is_active', MissingHindiFilter)
    search_fields = ('key', 'text_en', 'text_hi')
    fields = ('key', 'text_en', 'text_hi', 'is_active', 'created_date_time', 'updated_date_time')
    readonly_fields = ('created_date_time', 'updated_date_time')
    ordering = ('key',)
