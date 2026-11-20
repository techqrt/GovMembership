from django.urls import path

from gmp_apps.membership.controllers.id_card import MembershipIdCardViewController as IdCard
from gmp_apps.membership.controllers.permanent_application import MembershipPermanentApplicationViewController as Application
from gmp_apps.membership.controllers.progress import MembershipProgressViewController as Progress
from gmp_apps.membership.controllers.referral_invite import MembershipReferralInviteViewController as Invite
from gmp_apps.membership.controllers.referral import MembershipReferralViewController as Referral

urlpatterns = [
    path('progress/get/', Progress.get, name='get_membership_progress'),
    path('id_card/get/', IdCard.get, name='get_membership_id_card'),
    path('referral/get_all/', Referral.get_all, name='get_all_membership_referral'),
    path('referral_invite/create/', Invite.create, name='create_membership_referral_invite'),
    path('referral_invite/delete/', Invite.delete, name='delete_membership_referral_invite'),
    path('referral_invite/get_all/', Invite.get_all, name='get_all_membership_referral_invite'),
    path('permanent_application/create/', Application.create, name='create_membership_permanent_application'),
    path('permanent_application/get/', Application.get, name='get_membership_permanent_application'),
    path('permanent_application/get_all/', Application.get_all, name='get_all_membership_permanent_application'),
]
