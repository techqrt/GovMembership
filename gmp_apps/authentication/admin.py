from typing import Any

from django import forms
from django.contrib import admin, messages
from django.db.models import Count, Q, QuerySet
from django.http import HttpRequest
from unfold.admin import ModelAdmin
from unfold.decorators import display
from unfold.widgets import UnfoldAdminTextareaWidget

from gmp_apps.authentication.models import Otp, User
from gmp_apps.common.exceptions.errors import ForbiddenError

# Editable only by a superuser: who is staff, what role, which permission groups.
ACCESS_FIELDS = ('role', 'is_staff', 'is_superuser', 'groups', 'user_permissions')
# Editable only with the suspend_member permission.
STATUS_FIELDS = ('is_active', 'suspended_reason')


class MemberStatusForm(forms.ModelForm):
    """Suspension form: a reason is mandatory and the guard rules run before anything is saved."""

    acting_user: User  # set per request in UserAdmin.get_form

    class Meta:
        model = User
        fields = [*STATUS_FIELDS, *ACCESS_FIELDS]
        widgets = {'suspended_reason': UnfoldAdminTextareaWidget}

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        if 'is_active' in self.changed_data:
            try:
                User.assert_can_change_status(
                    self.acting_user, self.instance, bool(cleaned.get('is_active')), cleaned.get('suspended_reason') or '',
                )
            except (ValueError, ForbiddenError) as error:
                raise forms.ValidationError(str(error))
        return cleaned


@admin.register(User)
class UserAdmin(ModelAdmin):
    """Member search and view, suspend/reactivate, and access management.

    Profile data and the membership level are always read-only: the level only moves through the
    referral and Permanent-application rules. Members are suspended, never deleted.
    """

    form = MemberStatusForm
    list_display = ('membership_id', 'full_name', 'email', 'mobile_number', 'membership_level', 'role', 'is_active', 'created_date_time')
    list_filter = ('membership_level', 'role', 'is_active', 'email_verified', 'mobile_verified', 'is_staff')
    search_fields = ('membership_id', 'full_name', 'email', 'mobile_number', 'referral_code')
    ordering = ('-created_date_time',)
    filter_horizontal = ('groups', 'user_permissions')
    fieldsets = (
        ('Member', {'fields': (
            'membership_id', 'full_name', 'email', 'mobile_number', 'email_verified', 'mobile_verified',
            'date_of_birth', 'gender', 'state', 'city',
        )}),
        ('Membership', {'fields': ('membership_level', 'referral_code', 'verified_referrals', 'referred_by')}),
        ('Status', {'fields': ('is_active', 'suspended_reason', 'suspended_at')}),
        ('Access (superuser only)', {'fields': ACCESS_FIELDS}),
        ('Audit', {'fields': ('registration_ip', 'last_login', 'created_date_time')}),
    )
    always_readonly = (
        'membership_id', 'full_name', 'email', 'mobile_number', 'email_verified', 'mobile_verified', 'date_of_birth',
        'gender', 'state', 'city', 'membership_level', 'referral_code', 'verified_referrals', 'referred_by',
        'suspended_at', 'registration_ip', 'last_login', 'created_date_time',
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        qualifying = Count(
            'referrals_made', filter=Q(referrals_made__status='verified', referrals_made__referred__is_active=True),
        )
        return super().get_queryset(request).select_related('referral_received__referrer').annotate(verified_count=qualifying)

    def get_readonly_fields(self, request: HttpRequest, obj: User | None = None) -> tuple[str, ...]:
        readonly = list(self.always_readonly)
        if not request.user.is_superuser:
            readonly += ACCESS_FIELDS
        if not request.user.has_perm('authentication.suspend_member'):
            readonly += STATUS_FIELDS
        return tuple(readonly)

    def get_form(self, request: HttpRequest, obj: User | None = None, **kwargs: Any) -> type[forms.ModelForm]:
        form = super().get_form(request, obj, **kwargs)
        return type('MemberStatusRequestForm', (form,), {'acting_user': request.user})

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: User | None = None) -> bool:
        return False

    def save_model(self, request: HttpRequest, obj: User, form: forms.ModelForm, change: bool) -> None:
        """Status changes go through User.suspend/reactivate (reason, session revocation, guards);
        only whitelisted access fields are written otherwise."""
        original = User.objects.get(pk=obj.pk)
        reason = form.cleaned_data.get('suspended_reason') or ''
        try:
            if 'is_active' in form.changed_data:
                if obj.is_active:
                    original.reactivate(request.user)
                else:
                    original.suspend(request.user, reason)
                    messages.warning(request, 'Member suspended. All their sessions were revoked.')
            elif 'suspended_reason' in form.changed_data and not original.is_active:
                original.suspended_reason = reason
                original.save(update_fields=['suspended_reason'])
        except (ValueError, ForbiddenError) as error:
            messages.error(request, str(error))
            return
        writable = [f for f in form.changed_data if f in ACCESS_FIELDS and f not in ('groups', 'user_permissions')]
        if writable and request.user.is_superuser:
            fresh = User.objects.get(pk=obj.pk)
            for field in writable:
                setattr(fresh, field, getattr(obj, field))
            fresh.save(update_fields=writable)

    @display(description='Qualifying referrals', ordering='verified_count')
    def verified_referrals(self, obj: User) -> int:
        return obj.verified_count

    @display(description='Referred by')
    def referred_by(self, obj: User) -> str:
        record = getattr(obj, 'referral_received', None)
        return f'{record.referrer.full_name} ({record.referrer.membership_id})' if record else '-'


@admin.register(Otp)
class OtpAdmin(ModelAdmin):
    list_display = ('user', 'purpose', 'channel', 'is_used', 'expires_at')
    list_filter = ('purpose', 'channel', 'is_used')
    exclude = ('code_hash',)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False
