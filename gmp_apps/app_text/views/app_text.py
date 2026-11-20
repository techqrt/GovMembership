from rest_framework.response import Response

from gmp_apps.app_text.dataclasses.request.get_all.get_all_app_text import GetAllAppTextRequest
from gmp_apps.app_text.utils import AppTextUtils
from gmp_apps.common.common import Common
from gmp_apps.common.utils import Utils


class AppTextAppTextView:
    def __init__(self) -> None:
        self.data_get = 'Data fetched successfully'

    @Common().exception_handler
    def get_all_extract(self, params: GetAllAppTextRequest) -> Response:
        return Response(Utils.success_response_data(message=self.data_get, data=AppTextUtils.strings(params.language)))
