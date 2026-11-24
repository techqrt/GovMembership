import json
import logging
from typing import Any
from urllib.parse import urlsplit

from django import forms
from django.contrib import admin, messages
from django.contrib.admin import SimpleListFilter
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import action
from unfold.widgets import UnfoldAdminTextareaWidget

from gmp_apps.schemes.classification import classify
from gmp_apps.schemes.media_check import find_problems, requeue_media
from gmp_apps.schemes.tasks import sync_schemes
from gmp_apps.schemes.models import Scheme, SchemeDocument, SchemeExclusion, SchemeImage, SchemeSyncRun, SchemeTag
from gmp_apps.schemes.models.scheme import SchemeStatus

CONTENT_FIELDS = (
    'title', 'department', 'description', 'eligibility', 'benefits', 'application_procedure', 'required_documents',
    'highlights', 'contact_details',
)
STRUCTURED_FIELDS = ('links_text', 'overview_text', 'additional_text')
LINK_KINDS = ('website', 'brochure', 'link')
MAX_LINKS = 30
MAX_ROWS = 30
MAX_SECTIONS = 40
https_only = URLValidator(schemes=['https'])


class SchemeForm(forms.ModelForm):
    class Meta:
        model = Scheme
        fields = [*CONTENT_FIELDS, 'source_url']

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['links_text'].initial = '\n'.join(f"{l.get('kind', 'link')} | {l.get('label', '')} | {l.get('url', '')}" for l in self.instance.links or [])
            self.fields['overview_text'].initial = '\n'.join(f"{r.get('label', '')} | {r.get('value', '')}" for r in self.instance.overview or [])
            self.fields['additional_text'].initial = json.dumps(self.instance.additional_sections or [], ensure_ascii=False, indent=2)

    links_text = forms.CharField(
        required=False, label='Links (one per line: kind | label | https URL; kind is website, brochure or link)',
        widget=UnfoldAdminTextareaWidget(attrs={'rows': 5}),
    )
    overview_text = forms.CharField(
        required=False, label='Overview table (one row per line: label | value)', widget=UnfoldAdminTextareaWidget(attrs={'rows': 5}),
    )
    additional_text = forms.CharField(
        required=False, label='Additional sections (JSON list of {"heading": ..., "text": ...})',
        widget=UnfoldAdminTextareaWidget(attrs={'rows': 8}),
    )

    def clean_links_text(self) -> list[dict[str, str]]:
        links: list[dict[str, str]] = []
        for line in (self.cleaned_data.get('links_text') or '').splitlines():
            if not line.strip():
                continue
            parts = [part.strip() for part in line.split('|', 2)]
            if len(parts) != 3 or parts[0] not in LINK_KINDS:
                raise ValidationError(f'Use "kind | label | URL" with kind website, brochure or link: {line[:80]}')
            kind, label, link = parts
            parsed = urlsplit(link)
            if parsed.scheme not in ('http', 'https') or not parsed.netloc or len(link) > 500 or ' ' in link:
                raise ValidationError(f'Not a valid http(s) URL: {link[:80]}')
            links.append({'kind': kind, 'label': label[:200] or parsed.netloc, 'url': link})
        if len(links) > MAX_LINKS:
            raise ValidationError(f'At most {MAX_LINKS} links')
        return links

    def clean_overview_text(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for line in (self.cleaned_data.get('overview_text') or '').splitlines():
            if not line.strip():
                continue
            label, separator, value = line.partition('|')
            if not separator or not label.strip() or not value.strip():
                raise ValidationError(f'Use "label | value": {line[:80]}')
            rows.append({'label': label.strip()[:100], 'value': value.strip()[:500]})
        if len(rows) > MAX_ROWS:
            raise ValidationError(f'At most {MAX_ROWS} rows')
        return rows

    def clean_additional_text(self) -> list[dict[str, str]]:
        raw = (self.cleaned_data.get('additional_text') or '').strip()
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except ValueError:
            raise ValidationError('Not valid JSON')
        if not isinstance(data, list) or len(data) > MAX_SECTIONS:
            raise ValidationError(f'Expected a JSON list of at most {MAX_SECTIONS} sections')
        sections: list[dict[str, str]] = []
        for item in data:
            if not isinstance(item, dict) or not isinstance(item.get('heading'), str) or not isinstance(item.get('text'), str):
                raise ValidationError('Every section needs a text "heading" and "text"')
            sections.append({'heading': item['heading'][:200], 'text': item['text'][:20000]})
        return sections


class SchemeTagInline(TabularInline):
    """Classification tags (scheme type, person type, caste), shown to members and usable as filters."""

    model = SchemeTag
    extra = 1


class SchemeImageInline(TabularInline):
    """Pictures stored on this platform. Imported ones are downloaded by the sync; upload your own for
    manual schemes. Only JPEG, PNG, GIF and WebP up to the size limit are accepted (no SVG)."""

    model = SchemeImage
    extra = 1
    max_num = 10
    fields = ('file', 'position', 'source_url')
    readonly_fields = ('source_url',)

    def get_formset(self, request: HttpRequest, obj: Scheme | None = None, **kwargs: Any):
        # max_num alone only limits what is displayed; this makes the limit a real validation error.
        return super().get_formset(request, obj, validate_max=True, **kwargs)


class SchemeDocumentInline(TabularInline):
    """PDFs (brochure, guidelines) stored on this platform. Imported ones are downloaded by the sync;
    upload your own for manual schemes. Only real PDF files up to the size limit are accepted."""

    model = SchemeDocument
    extra = 1
    max_num = 10
    fields = ('file', 'label', 'kind', 'position', 'source_url')
    readonly_fields = ('source_url',)

    def get_formset(self, request: HttpRequest, obj: Scheme | None = None, **kwargs: Any):
        return super().get_formset(request, obj, validate_max=True, **kwargs)


class MediaStatusFilter(SimpleListFilter):
    """Imported schemes whose pictures/PDFs are verified, or still waiting (retried by the next sync)."""

    title = 'pictures and PDFs'
    parameter_name = 'media'

    def lookups(self, request: HttpRequest, model_admin: ModelAdmin) -> list[tuple[str, str]]:
        return [('pending', 'Waiting for sync'), ('verified', 'Verified'), ('admin', 'Managed by an admin')]

    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        owned = queryset.filter(source_url__isnull=False, is_manual=False, locally_edited=False)
        if self.value() == 'pending':
            return owned.filter(media_synced_at__isnull=True)
        if self.value() == 'verified':
            return owned.filter(media_synced_at__isnull=False)
        if self.value() == 'admin':
            return queryset.filter(is_manual=True) | queryset.filter(locally_edited=True)
        return queryset

class NeedsLevelFilter(SimpleListFilter):
    """Schemes with no national/state level yet: they are listed to members but match neither filter."""

    title = 'national / state'
    parameter_name = 'needs_level'

    def lookups(self, request: HttpRequest, model_admin: ModelAdmin) -> list[tuple[str, str]]:
        return [('missing', 'Level not set yet')]

    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        return queryset.filter(level='') if self.value() == 'missing' else queryset


logger = logging.getLogger(__name__)


@admin.register(Scheme)
class SchemeAdmin(ModelAdmin):
    """Review queue and editor for government initiatives.

    Imports arrive as 'pending review'. Publish, unpublish and edit here; add manually when the
    automatic import cannot reach something. Editing an imported scheme protects it from being
    overwritten by the next sync (use 'Release local edits' to hand it back). Deleting removes
    only our local record and blocks re-import of that source URL.
    """

    form = SchemeForm
    inlines = [SchemeTagInline, SchemeImageInline, SchemeDocumentInline]
    list_display = ('title', 'department', 'level', 'state', 'status', 'is_accepting_applications', 'media_status', 'is_manual', 'locally_edited', 'last_synced_at', 'updated_date_time')
    list_filter = ('status', NeedsLevelFilter, 'level', 'state', 'is_accepting_applications', MediaStatusFilter, 'is_manual', 'locally_edited')
    search_fields = ('title', 'department', 'source_url', 'description')
    ordering = ('-updated_date_time',)
    actions = ['publish_selected', 'unpublish_selected', 'release_local_edits', 'requeue_media_selected', 'fill_level_selected']
    actions_list = ['check_media']
    fieldsets = (
        ('Content', {'fields': CONTENT_FIELDS}),
        ('Source', {'fields': ('source_url', 'links_text')}),
        ('Details', {'fields': ('overview_text', 'additional_text')}),
        ('Review', {'fields': ('status', 'level', 'state', 'is_accepting_applications', 'is_manual', 'locally_edited', 'reviewed_by', 'published_date_time')}),
        ('Sync', {'fields': ('last_synced_at', 'media_synced_at', 'source_lastmod', 'created_date_time', 'updated_date_time')}),
    )
    review_fields = (
        'status', 'is_manual', 'locally_edited', 'reviewed_by', 'published_date_time', 'last_synced_at', 'media_synced_at',
        'source_lastmod', 'created_date_time', 'updated_date_time',
    )

    @admin.display(description='Pictures/PDFs')
    def media_status(self, obj: Scheme) -> str:  # not named `media`: that is a ModelAdmin property
        if obj.is_manual or obj.locally_edited:
            return 'admin-managed'
        return 'verified' if obj.media_synced_at else 'waiting for sync'

    def get_readonly_fields(self, request: HttpRequest, obj: Scheme | None = None) -> tuple[str, ...]:
        readonly = list(self.review_fields)
        if obj is not None and obj.source_url:
            readonly.append('source_url')  # the identity of an imported scheme never changes
        return tuple(readonly)

    def save_model(self, request: HttpRequest, obj: Scheme, form: forms.ModelForm, change: bool) -> None:
        obj.links = form.cleaned_data.get('links_text', obj.links)
        obj.overview = form.cleaned_data.get('overview_text', obj.overview)
        obj.additional_sections = form.cleaned_data.get('additional_text', obj.additional_sections)
        if not change:
            obj.is_manual = True
            obj.reviewed_by = request.user
        elif obj.source_url and not obj.is_manual and set(form.changed_data) & {*CONTENT_FIELDS, *STRUCTURED_FIELDS}:
            obj.locally_edited = True
            messages.info(request, 'This imported scheme is now protected: the next sync will not overwrite your edits.')
        obj.save()

    def save_related(self, request: HttpRequest, form: forms.ModelForm, formsets: list[Any], change: bool) -> None:
        super().save_related(request, form, formsets, change)
        scheme = form.instance
        if change and scheme.source_url and not scheme.is_manual and not scheme.locally_edited and any(fs.has_changed() for fs in formsets):
            Scheme.objects.filter(pk=scheme.pk).update(locally_edited=True)  # tag, image and document edits protect the scheme too

    def delete_model(self, request: HttpRequest, obj: Scheme) -> None:
        Scheme.remove(obj.pk, request.user, reason='Deleted in the admin')

    def delete_queryset(self, request: HttpRequest, queryset: QuerySet) -> None:
        for scheme_id in list(queryset.values_list('pk', flat=True)):
            Scheme.remove(scheme_id, request.user, reason='Deleted in the admin')

    @action(description='Publish selected schemes', permissions=['publish'])
    def publish_selected(self, request: HttpRequest, queryset: QuerySet) -> None:
        # A scheme needs some real content before members can see it.
        publishable = queryset.exclude(status=SchemeStatus.PUBLISHED).exclude(description='', benefits='', eligibility='')
        skipped = queryset.exclude(status=SchemeStatus.PUBLISHED).count() - publishable.count()
        now = timezone.now()
        ids = list(publishable.values_list('pk', flat=True))
        Scheme.objects.filter(pk__in=ids, published_date_time__isnull=True).update(published_date_time=now)
        Scheme.objects.filter(pk__in=ids).update(status=SchemeStatus.PUBLISHED, reviewed_by=request.user, updated_date_time=now)
        note = f' {skipped} had no description, benefits or eligibility and were skipped.' if skipped else ''
        waiting = Scheme.objects.filter(pk__in=ids, source_url__isnull=False, is_manual=False, locally_edited=False, media_synced_at__isnull=True).count()
        if waiting:
            note += f' Warning: {waiting} are still waiting for their pictures/PDFs (the next sync fills them in).'
        self.message_user(request, f'{len(ids)} scheme(s) published.{note}')

    @action(description='Unpublish selected schemes', permissions=['publish'])
    def unpublish_selected(self, request: HttpRequest, queryset: QuerySet) -> None:
        count = queryset.filter(status=SchemeStatus.PUBLISHED).update(
            status=SchemeStatus.UNPUBLISHED, reviewed_by=request.user, updated_date_time=timezone.now(),
        )
        self.message_user(request, f'{count} scheme(s) unpublished.')

    @action(description='Release local edits (the next sync may overwrite them)', permissions=['change'])
    def release_local_edits(self, request: HttpRequest, queryset: QuerySet) -> None:
        count = queryset.filter(locally_edited=True, is_manual=False).update(locally_edited=False, source_lastmod=None)
        self.message_user(request, f'{count} scheme(s) released. They will be re-fetched on the next sync.')

    @action(description='Re-fetch pictures/PDFs of selected schemes at the next sync', permissions=['change'])
    def requeue_media_selected(self, request: HttpRequest, queryset: QuerySet) -> None:
        problems = {pk: ['re-fetch requested'] for pk in queryset.values_list('pk', flat=True)}
        owned, removed = requeue_media(problems)
        skipped = len(problems) - len(owned)
        note = f' {skipped} are managed by an admin (edited or manual): replace their files by hand.' if skipped else ''
        self.message_user(request, f'{len(owned)} scheme(s) will have their pictures/PDFs fetched again by the next sync ({removed} broken file record(s) removed).{note}')

    @action(description='Fill level and state from the rules (only schemes with none set)', permissions=['change'])
    def fill_level_selected(self, request: HttpRequest, queryset: QuerySet) -> None:
        """Only schemes with no level yet; a level that is set is never touched. A queryset update, so no scheme
        is marked as edited and its content, status and 'updated' time stay exactly as they were."""
        filled = unclear = 0
        for pk, department, title, source_url in list(queryset.filter(level='').values_list('pk', 'department', 'title', 'source_url')):
            guess = classify(department, title, source_url)
            if guess.level:
                Scheme.objects.filter(pk=pk, level='').update(level=guess.level, state=guess.state)
                filled += 1
            else:
                unclear += 1
        self.message_user(request, f'{filled} scheme(s) filled in. {unclear} could not be told from their text: set those by hand.')

    @action(description='Check pictures and PDFs', permissions=['view'], url_path='check-media')
    def check_media(self, request: HttpRequest) -> HttpResponse:
        """Read-only health check: every imported scheme has the pictures/PDFs its page promised and the files exist."""
        problems = find_problems()
        if not problems:
            messages.success(request, 'All imported schemes have their pictures and PDFs.')
        else:
            titles = dict(Scheme.objects.filter(pk__in=list(problems)[:5]).values_list('pk', 'title'))
            examples = '; '.join(f'{titles.get(pk, pk)}: {problems[pk][0]}' for pk in list(problems)[:5])
            messages.warning(request, f'{len(problems)} scheme(s) have missing or unverified pictures/PDFs. Examples: {examples}. '
                                      'Filter by "Waiting for sync", then use "Re-fetch pictures/PDFs" and start a sync.')
        return redirect(reverse('admin:schemes_scheme_changelist'))

    def has_publish_permission(self, request: HttpRequest) -> bool:
        return request.user.has_perm('schemes.publish_scheme')


@admin.register(SchemeExclusion)
class SchemeExclusionAdmin(ModelAdmin):
    """URLs deleted by an admin. Delete an entry here to let the sync import that scheme again."""

    list_display = ('source_url', 'reason', 'excluded_by', 'created_date_time')
    search_fields = ('source_url', 'reason')

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: SchemeExclusion | None = None) -> bool:
        return False


@admin.register(SchemeSyncRun)
class SchemeSyncRunAdmin(ModelAdmin):
    """Log of every scheme sync (the daily Celery Beat run and manual imports). Read-only.

    The "Start sync now" button (needs the run_scheme_sync permission) asks for confirmation and
    queues the same job the daily schedule runs. It never starts a second run on top of one.
    """

    list_display = ('run_id', 'trigger', 'status', 'started_date_time', 'duration', 'created', 'updated', 'unchanged', 'errors', 'media_pending')
    list_filter = ('status', 'trigger')
    actions_list = ['sync_now']

    @admin.display(description='Duration')
    def duration(self, obj: SchemeSyncRun) -> str:
        if obj.finished_date_time is None:
            return '-'
        seconds = int((obj.finished_date_time - obj.started_date_time).total_seconds())
        return f'{seconds // 60}m {seconds % 60}s'

    @action(description='Start sync now', permissions=['run_scheme_sync'], url_path='sync-now')
    def sync_now(self, request: HttpRequest) -> HttpResponse:
        back = reverse('admin:schemes_schemesyncrun_changelist')
        busy = SchemeSyncRun.is_busy()
        if request.method != 'POST':  # a link click must never start a job: show a confirmation form
            context = {**self.admin_site.each_context(request), 'title': 'Start a scheme sync', 'busy': busy, 'back_url': back}
            return TemplateResponse(request, 'admin/schemes/sync_confirm.html', context)
        if busy:
            messages.warning(request, 'A sync is already running. Wait for it to finish.')
            return redirect(back)
        try:
            sync_schemes.delay()
        except Exception:  # noqa: BLE001 - the broker (Redis) is down or misconfigured
            logger.exception('Could not queue a scheme sync')
            messages.error(request, 'The sync could not be queued. Check that Redis and the Celery worker are running.')
            return redirect(back)
        messages.success(request, 'Sync queued. Refresh this page in a few minutes to see the run appear.')
        return redirect(back)

    def has_run_scheme_sync_permission(self, request: HttpRequest) -> bool:
        return request.user.has_perm('schemes.run_scheme_sync')

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: SchemeSyncRun | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: SchemeSyncRun | None = None) -> bool:
        return False
