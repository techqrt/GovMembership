from gmp_apps.membership.serializers.response.get.get_permanent_application import (
    PermanentApplicationResponseGetSerializer,
)
from gmp_apps.membership.serializers.response.get_all.get_all_referral import PageSerializer


class PermanentApplicationResponseGetAllSerializer(PageSerializer):
    data = PermanentApplicationResponseGetSerializer(many=True)
