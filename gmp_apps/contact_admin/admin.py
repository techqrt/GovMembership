from typing import Any

from django import forms
from django.contrib import admin, messages
from django.http import HttpRequest
from unfold.admin import ModelAdmin
from unfold.decorators import display
from unfold.widgets import UnfoldAdminSelectWidget, UnfoldAdminTextareaWidget

from gmp_apps.common.exceptions.errors import NotFoundError
from gmp_apps.contact_admin.models import ContactCategory, ContactRequest
from gmp_apps.contact_admin.models.contact_request import RequestStatus


class ContactRequestForm(forms.ModelForm):
    """Admin can only set the status and write the reply; what the member sent is read-only."""

    status = forms.ChoiceField(choices=RequestStatus.choices, widget=UnfoldAdminSelectWidget)

    class Meta:
        model = ContactRequest
        fields = ['status', 'admin_reply']
        widgets = {'admin_reply': UnfoldAdminTextareaWidget}

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        if self.instance.pk and {'status', 'admin_reply'} & set(self.changed_data):
            reply = (cleaned.get('admin_reply') or '').strip()
            status = cleaned.get('status') or ''
            if reply and status == RequestStatus.OPEN:
                status = RequestStatus.IN_PROGRESS
            try:
                ContactRequest.check_response(self.instance.status, status, reply)
            except ValueError as error:
                raise forms.ValidationError(str(error))
        return cleaned


@admin.register(ContactRequest)
class ContactRequestAdmin(ModelAdmin):
    """Incoming Contact Admin requests: read, reply, set status. Requests are never added or deleted here."""

    form = ContactRequestForm
    list_display = ('request_id', 'member', 'category', 'subject', 'status', 'created_date_time')
    list_filter = ('status', 'category')
    search_fields = ('subject', 'description', 'user__full_name', 'user__membership_id', 'user__email', 'user__mobile_number')
    list_select_related = ('user', 'category')
    ordering = ('-created_date_time',)
    fields = (
        'user', 'category', 'subject', 'description', 'created_date_time', 'status', 'admin_reply', 'replied_by',
        'replied_date_time',
    )
    readonly_fields = ('user', 'category', 'subject', 'description', 'created_date_time', 'replied_by', 'replied_date_time')

    @display(description='Member', ordering='user__full_name')
    def member(self, obj: ContactRequest) -> str:
        return f'{obj.user.full_name} ({obj.user.membership_id})'

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: ContactRequest | None = None) -> bool:
        return False

    def save_model(self, request: HttpRequest, obj: ContactRequest, form: forms.ModelForm, change: bool) -> None:
        try:
            ContactRequest.respond(obj.pk, request.user, form.cleaned_data['status'], form.cleaned_data.get('admin_reply') or '')
        except (ValueError, NotFoundError) as error:
            messages.error(request, str(error))
            return
        obj.refresh_from_db()


@admin.register(ContactCategory)
class ContactCategoryAdmin(ModelAdmin):
    """Categories members can pick. Deactivate instead of deleting: old requests keep their category."""

    list_display = ('name', 'sort_order', 'is_active')
    list_editable = ('sort_order', 'is_active')
    search_fields = ('name',)

    def has_delete_permission(self, request: HttpRequest, obj: ContactCategory | None = None) -> bool:
        return False
