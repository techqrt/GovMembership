from gmp_apps.membership.serializers.response.get.get_referral_invite import ReferralInviteResponseGetSerializer
from gmp_apps.membership.serializers.response.get_all.get_all_referral import PageSerializer


class ReferralInviteResponseGetAllSerializer(PageSerializer):
    data = ReferralInviteResponseGetSerializer(many=True)
