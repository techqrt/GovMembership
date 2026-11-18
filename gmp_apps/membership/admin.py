from typing import Any

from django import forms
from django.contrib import admin, messages
from django.db.models import Count, Q, QuerySet
from django.http import HttpRequest
from unfold.admin import ModelAdmin
from unfold.decorators import action, display
from unfold.widgets import UnfoldAdminSelectWidget, UnfoldAdminTextareaWidget

from gmp.config import Configurations
from gmp.constants import Constants
from gmp_apps.common.exceptions.errors import NotFoundError
from gmp_apps.membership.models import PermanentApplication, Referral, ReferralInvite
from gmp_apps.membership.models.permanent_application import ApplicationStatus
from gmp_apps.membership.models.referral import ReferralStatus
from gmp_apps.membership.models.referral_invite import InviteStatus, default_invite_expiry

DECISIONS = [('', '---------'), ('approve', 'Approve'), ('reject', 'Reject')]


class ReviewForm(forms.ModelForm):
    """Decision form shared by referral and Permanent-application review.

    Everything about the record is read-only; an admin can only set a decision and remarks. The
    rules themselves (who may be decided, remarks on reject, Permanent only on approval) are
    enforced by `Referral.review` / `PermanentApplication.review`, the single implementation.
    """

    decision = forms.ChoiceField(choices=DECISIONS, required=False, widget=UnfoldAdminSelectWidget)

    class Meta:
        fields = ['admin_remarks']
        widgets = {'admin_remarks': UnfoldAdminTextareaWidget}

    def is_open(self) -> bool:
        raise NotImplementedError

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        if not self.instance.pk:
            return cleaned
        decision, remarks = cleaned.get('decision'), cleaned.get('admin_remarks') or ''
        if not self.is_open():
            if decision or 'admin_remarks' in self.changed_data:
                raise forms.ValidationError('This record has already been decided and cannot be changed.')
        elif decision == 'reject' and not remarks.strip():
            self.add_error('admin_remarks', Constants.remarks_required)
        return cleaned


class ReferralReviewForm(ReviewForm):
    class Meta(ReviewForm.Meta):
        model = Referral

    def is_open(self) -> bool:
        return self.instance.status == ReferralStatus.FLAGGED


class ApplicationReviewForm(ReviewForm):
    class Meta(ReviewForm.Meta):
        model = PermanentApplication

    def is_open(self) -> bool:
        return self.instance.status == ApplicationStatus.PENDING


class ReviewAdminMixin:
    """No adding or deleting (audit data); saving applies the decision through the model's review()."""

    review_function: Any = None

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def save_model(self, request: HttpRequest, obj: Any, form: forms.ModelForm, change: bool) -> None:
        decision = form.cleaned_data.get('decision')
        if not decision:
            if 'admin_remarks' in form.changed_data:
                obj.save(update_fields=['admin_remarks'])
            return
        try:
            type(self).review_function(obj.pk, request.user, decision, form.cleaned_data.get('admin_remarks') or '')
        except (ValueError, NotFoundError) as error:
            messages.error(request, str(error))
            return
        obj.refresh_from_db()
        messages.success(request, f'Decision "{decision}" recorded.')


@admin.register(Referral)
class ReferralAdmin(ReviewAdminMixin, ModelAdmin):
    """Fraud-flagged referrals wait here. Filter by status 'flagged', open one, choose approve or reject."""

    form = ReferralReviewForm
    review_function = staticmethod(Referral.review)
    list_display = ('referral_id', 'referrer', 'referred', 'status', 'flag_reason', 'created_date_time')
    list_filter = ('status',)
    search_fields = ('referrer__membership_id', 'referrer__full_name', 'referred__membership_id', 'referred__full_name')
    list_select_related = ('referrer', 'referred')
    fields = (
        'referrer', 'referred', 'status', 'flag_reason', 'registered_from_ip', 'verified_date_time',
        'reviewed_by', 'reviewed_date_time', 'created_date_time', 'decision', 'admin_remarks',
    )
    readonly_fields = (
        'referrer', 'referred', 'status', 'flag_reason', 'registered_from_ip', 'verified_date_time',
        'reviewed_by', 'reviewed_date_time', 'created_date_time',
    )

    @admin.display(description='Referred member IP')
    def registered_from_ip(self, obj: Referral) -> str | None:
        return obj.referred.registration_ip


@admin.register(PermanentApplication)
class PermanentApplicationAdmin(ReviewAdminMixin, ModelAdmin):
    """Permanent membership is granted only by approving a pending application here."""

    form = ApplicationReviewForm
    review_function = staticmethod(PermanentApplication.review)
    list_display = ('application_id', 'member', 'member_level', 'verified_referrals', 'status', 'created_date_time')
    list_filter = ('status',)
    search_fields = ('user__membership_id', 'user__full_name', 'user__email', 'user__mobile_number')
    list_select_related = ('user',)
    fields = (
        'user', 'member_level', 'verified_referrals', 'reason', 'status', 'reviewed_by', 'reviewed_date_time',
        'created_date_time', 'decision', 'admin_remarks',
    )
    readonly_fields = (
        'user', 'member_level', 'verified_referrals', 'reason', 'status', 'reviewed_by', 'reviewed_date_time',
        'created_date_time',
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        qualifying = Count(
            'user__referrals_made',
            filter=Q(user__referrals_made__status=ReferralStatus.VERIFIED, user__referrals_made__referred__is_active=True),
        )
        return super().get_queryset(request).annotate(verified_count=qualifying)

    @display(description='Member', ordering='user__full_name')
    def member(self, obj: PermanentApplication) -> str:
        return f'{obj.user.full_name} ({obj.user.membership_id})'

    @display(description='Level', ordering='user__membership_level')
    def member_level(self, obj: PermanentApplication) -> str:
        return obj.user.membership_level

    @display(description='Verified referrals', ordering='verified_count')
    def verified_referrals(self, obj: PermanentApplication) -> int:
        return obj.verified_count


@admin.register(ReferralInvite)
class ReferralInviteAdmin(ModelAdmin):
    """Admin side of referral invitations: view, and cancel or extend through actions only.

    Fields are read-only so every change goes through an action that keeps the one-open-invite-per-
    contact rule intact. Expiry also runs on a timer (Celery Beat) and lazily when this list opens.
    """

    list_display = ('invite_id', 'referrer', 'full_name', 'email', 'mobile_number', 'status', 'expires_at', 'created_date_time')
    list_filter = ('status',)
    search_fields = ('full_name', 'email', 'mobile_number', 'referrer__membership_id', 'referrer__full_name')
    readonly_fields = ('referrer', 'full_name', 'email', 'mobile_number', 'status', 'expires_at', 'created_date_time')
    actions = ['cancel_invites', 'extend_expiry']

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        ReferralInvite.expire_due()
        return super().get_queryset(request)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    @action(description='Cancel selected open invitations', permissions=['change'])
    def cancel_invites(self, request: HttpRequest, queryset: QuerySet) -> None:
        changed = queryset.filter(status=InviteStatus.INVITED).update(status=InviteStatus.CANCELLED)
        self.message_user(request, f'{changed} open invitation(s) cancelled. Other statuses were left unchanged.')

    @action(description='Extend expiry of selected open invitations', permissions=['change'])
    def extend_expiry(self, request: HttpRequest, queryset: QuerySet) -> None:
        changed = queryset.filter(status=InviteStatus.INVITED).update(expires_at=default_invite_expiry())
        self.message_user(
            request,
            f'{changed} open invitation(s) extended by {Configurations.referral_invite_ttl_days} days from now. '
            'Expired, cancelled and registered ones cannot be extended.',
        )
