from typing import Any

from django import forms
from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from django.db.models import Q, QuerySet
from django.http import HttpRequest
from django.utils import timezone
from unfold.admin import ModelAdmin
from unfold.decorators import action, display
from unfold.widgets import UnfoldAdminTextareaWidget

from gmp_apps.content.models import ContentCategory, ContentItem
from gmp_apps.content.models.content_item import ContentStatus


class ContentItemForm(forms.ModelForm):
    class Meta:
        model = ContentItem
        fields = [
            'content_type', 'title', 'summary', 'body', 'category', 'cover_image', 'video_url', 'duration_seconds', 'min_level', 'is_pinned',
            'status', 'publish_at', 'expire_at',
        ]
        widgets = {'body': UnfoldAdminTextareaWidget(attrs={'rows': 12}), 'summary': UnfoldAdminTextareaWidget(attrs={'rows': 3})}
        help_texts = {
            'body': 'Plain text only; line breaks are kept.',
            'duration_seconds': 'Optional, videos only: the length in seconds (for example 754 for 12 min 34 s).',
            'video_url': 'Link to a video on an allowed host (YouTube, Vimeo by default). Videos are never hosted here.',
            'min_level': 'Members below this level cannot see the item at all.',
            'publish_at': 'Go-live time. Leave empty to go live as soon as it is published. A future time schedules it.',
            'expire_at': 'Optional. After this time members no longer see the item.',
        }


class VisibilityFilter(SimpleListFilter):
    """Where an item is in its life, computed from status and schedule."""

    title = 'visibility now'
    parameter_name = 'visibility'

    def lookups(self, request: HttpRequest, model_admin: ModelAdmin) -> list[tuple[str, str]]:
        return [('live', 'Live'), ('scheduled', 'Scheduled'), ('expired', 'Expired')]

    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        now = timezone.now()
        published = queryset.filter(status=ContentStatus.PUBLISHED)
        if self.value() == 'live':
            return published.filter(publish_at__lte=now).filter(Q(expire_at__isnull=True) | Q(expire_at__gt=now))
        if self.value() == 'scheduled':
            return published.filter(publish_at__gt=now)
        if self.value() == 'expired':
            return published.filter(expire_at__lte=now)
        return queryset


@admin.register(ContentItem)
class ContentItemAdmin(ModelAdmin):
    """Content management. Editors write drafts; only people with the publish permission can publish,
    schedule, unpublish or archive. Restrict an item to a membership level with 'minimum level'."""

    form = ContentItemForm
    list_display = ('title', 'content_type', 'category', 'min_level', 'state_now', 'is_pinned', 'publish_at', 'expire_at', 'updated_date_time')
    list_filter = ('content_type', 'status', VisibilityFilter, 'category', 'min_level', 'is_pinned')
    search_fields = ('title', 'summary', 'body', 'category__name')
    list_select_related = ('category',)
    ordering = ('-updated_date_time',)
    actions = ['publish_selected', 'unpublish_selected', 'archive_selected']

    @display(description='State')
    def state_now(self, obj: ContentItem) -> str:
        return obj.state()

    def has_publish_permission(self, request: HttpRequest) -> bool:
        return request.user.has_perm('content.publish_contentitem')

    def get_readonly_fields(self, request: HttpRequest, obj: ContentItem | None = None) -> tuple[str, ...]:
        return () if self.has_publish_permission(request) else ('status',)

    def save_model(self, request: HttpRequest, obj: ContentItem, form: forms.ModelForm, change: bool) -> None:
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @action(description='Publish selected (goes live at its go-live time, or now)', permissions=['publish'])
    def publish_selected(self, request: HttpRequest, queryset: QuerySet) -> None:
        ready = queryset.exclude(status=ContentStatus.PUBLISHED).exclude(body='', summary='', video_url='')
        skipped = queryset.exclude(status=ContentStatus.PUBLISHED).count() - ready.count()
        count = 0
        for item in ready:  # per item: save() sets the go-live time
            item.status = ContentStatus.PUBLISHED
            item.save()
            count += 1
        note = f' {skipped} had no body, summary or video and were skipped.' if skipped else ''
        self.message_user(request, f'{count} item(s) published.{note}')

    @action(description='Unpublish selected (back to draft)', permissions=['publish'])
    def unpublish_selected(self, request: HttpRequest, queryset: QuerySet) -> None:
        count = queryset.filter(status=ContentStatus.PUBLISHED).update(status=ContentStatus.DRAFT, updated_date_time=timezone.now())
        self.message_user(request, f'{count} item(s) unpublished.')

    @action(description='Archive selected (hidden, kept for the record)', permissions=['publish'])
    def archive_selected(self, request: HttpRequest, queryset: QuerySet) -> None:
        count = queryset.exclude(status=ContentStatus.ARCHIVED).update(status=ContentStatus.ARCHIVED, updated_date_time=timezone.now())
        self.message_user(request, f'{count} item(s) archived.')


@admin.register(ContentCategory)
class ContentCategoryAdmin(ModelAdmin):
    """Content categories. Deactivating one hides all its content from members. A category that still has
    content cannot be deleted (deactivate it, or move/delete its content first)."""

    list_display = ('name', 'sort_order', 'is_active', 'item_count')
    list_editable = ('sort_order', 'is_active')
    search_fields = ('name',)

    @display(description='Items')
    def item_count(self, obj: ContentCategory) -> Any:
        return obj.items.count()
