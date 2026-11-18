from typing import Any

from django import forms
from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils import timezone
from unfold.admin import ModelAdmin
from unfold.decorators import action, display
from unfold.widgets import UnfoldAdminTextareaWidget

from gmp_apps.chatbot.models import ChatLog, KnowledgeEntry
from gmp_apps.chatbot.models.knowledge_entry import EntryStatus
from gmp_apps.chatbot.validators import SCREENS, validate_links

CONTENT_FIELDS = {'question', 'answer', 'language', 'links_text', 'screens'}


class KnowledgeEntryForm(forms.ModelForm):
    links_text = forms.CharField(
        required=False, label='Curated links (one per line: label | https URL)', widget=UnfoldAdminTextareaWidget(attrs={'rows': 4}),
    )
    screens = forms.MultipleChoiceField(
        required=False, choices=[(s, s.replace('_', ' ').capitalize()) for s in SCREENS], widget=forms.CheckboxSelectMultiple,
        help_text='Screens of the app the assistant can point the member to.',
    )

    class Meta:
        model = KnowledgeEntry
        fields = ['question', 'answer', 'language', 'category', 'sort_order', 'status']
        widgets = {'answer': UnfoldAdminTextareaWidget(attrs={'rows': 6})}
        help_texts = {
            'answer': 'Exactly what members should be told. If a member asks in another language the assistant translates THIS text; it adds nothing.',
            'language': 'Language this answer is written in (en, hi, ...). Members writing in the same language get this text word for word.',
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['links_text'].initial = '\n'.join(f"{l['label']} | {l['url']}" for l in self.instance.links or [])
            self.fields['screens'].initial = self.instance.screens or []

    def clean_links_text(self) -> list[dict[str, str]]:
        links: list[dict[str, str]] = []
        for line in (self.cleaned_data.get('links_text') or '').splitlines():
            if not line.strip():
                continue
            label, separator, url = line.partition('|')
            if not separator:
                raise forms.ValidationError(f'Use "label | https URL": {line[:80]}')
            links.append({'label': label.strip(), 'url': url.strip()})
        validate_links(links)
        return links


@admin.register(KnowledgeEntry)
class KnowledgeEntryAdmin(ModelAdmin):
    """The approved knowledge base: the ONLY source the chatbot answers from. Editors write drafts; approvers
    approve or retire. Changing the text of an approved entry without the approve permission sends it back to
    draft, so unapproved wording never reaches members."""

    form = KnowledgeEntryForm
    list_display = ('question', 'category', 'language', 'status', 'link_count', 'updated_date_time')
    list_filter = ('status', 'language', 'category')
    search_fields = ('question', 'answer', 'category')
    ordering = ('sort_order', 'entry_id')
    actions = ['approve_selected', 'retire_selected', 'draft_selected']

    @display(description='Links')
    def link_count(self, obj: KnowledgeEntry) -> int:
        return len(obj.links or [])

    def has_approve_permission(self, request: HttpRequest) -> bool:
        return request.user.has_perm('chatbot.approve_knowledgeentry')

    def get_readonly_fields(self, request: HttpRequest, obj: KnowledgeEntry | None = None) -> tuple[str, ...]:
        return () if self.has_approve_permission(request) else ('status',)

    def save_model(self, request: HttpRequest, obj: KnowledgeEntry, form: forms.ModelForm, change: bool) -> None:
        obj.links = form.cleaned_data.get('links_text', obj.links)
        obj.screens = form.cleaned_data.get('screens', obj.screens)
        if not change:
            obj.created_by = request.user
        elif not self.has_approve_permission(request) and set(form.changed_data) & CONTENT_FIELDS:
            was = KnowledgeEntry.objects.filter(pk=obj.pk).values_list('status', flat=True).first()
            if was == EntryStatus.APPROVED:
                obj.status = EntryStatus.DRAFT
                messages.warning(request, 'The text of an approved entry changed, so it went back to draft until an approver approves it again.')
        if obj.status == EntryStatus.APPROVED and obj.approved_by_id is None:
            obj.approved_by, obj.approved_date_time = request.user, timezone.now()
        super().save_model(request, obj, form, change)

    @action(description='Approve selected (the chatbot may use them)', permissions=['approve'])
    def approve_selected(self, request: HttpRequest, queryset: QuerySet) -> None:
        count = queryset.exclude(status=EntryStatus.APPROVED).update(
            status=EntryStatus.APPROVED, approved_by=request.user, approved_date_time=timezone.now(), updated_date_time=timezone.now(),
        )
        self.message_user(request, f'{count} entr{"y" if count == 1 else "ies"} approved.')

    @action(description='Retire selected (the chatbot stops using them)', permissions=['approve'])
    def retire_selected(self, request: HttpRequest, queryset: QuerySet) -> None:
        count = queryset.filter(status=EntryStatus.APPROVED).update(status=EntryStatus.RETIRED, updated_date_time=timezone.now())
        self.message_user(request, f'{count} entr{"y" if count == 1 else "ies"} retired.')

    @action(description='Send selected back to draft', permissions=['approve'])
    def draft_selected(self, request: HttpRequest, queryset: QuerySet) -> None:
        count = queryset.exclude(status=EntryStatus.DRAFT).update(status=EntryStatus.DRAFT, updated_date_time=timezone.now())
        self.message_user(request, f'{count} entr{"y" if count == 1 else "ies"} sent back to draft.')


@admin.register(ChatLog)
class ChatLogAdmin(ModelAdmin):
    """What members asked and how the assistant responded. Read-only; old logs are purged automatically. Use the
    'No approved answer' outcome to find questions the knowledge base is missing."""

    list_display = ('created_date_time', 'outcome', 'language', 'short_question', 'reason', 'member')
    list_filter = ('outcome', 'language')
    search_fields = ('question', 'reply', 'user__membership_id')
    list_select_related = ('user',)
    readonly_fields = ('user', 'question', 'language', 'outcome', 'reason', 'entry_ids', 'reply', 'created_date_time')

    @display(description='Question')
    def short_question(self, obj: ChatLog) -> str:
        return obj.question[:70]

    @display(description='Member')
    def member(self, obj: ChatLog) -> str:
        return obj.user.membership_id

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: ChatLog | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: ChatLog | None = None) -> bool:
        return False
