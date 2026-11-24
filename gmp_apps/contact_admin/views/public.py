from django.db import transaction
from rest_framework.response import Response

from gmp.constants import Constants
from gmp_apps.common.common import Common
from gmp_apps.common.utils import Utils
from gmp_apps.contact_admin.dataclasses.request.create.create_public_request import CreatePublicRequestRequest
from gmp_apps.contact_admin.models import ContactCategory, ContactRequest
from gmp_apps.contact_admin.utils import ContactAdminUtils


class ContactPublicView:
    """The Contact Us form for visitors who are not logged in. Nothing is ever read back: the reply is a plain 'received'."""

    def __init__(self) -> None:
        self.data_create = Constants.contact_public_received
        self.data_get = 'Data fetched successfully'

    @Common().exception_handler
    def create_extract(self, params: CreatePublicRequestRequest) -> Response:
        """A filled honeypot gets the same answer as a real submission and is not stored, so a bot learns nothing."""
        if not params.website:
            category = ContactCategory.objects.get(category_id=params.category_id, is_active=True)
            with transaction.atomic():
                ContactRequest.create_public(
                    category=category, full_name=params.full_name.strip(), email=params.email, mobile_number=params.mobile_number,
                    subject=params.subject, description=params.description.strip(),
                )
        return Response(Utils.success_response_data(message=self.data_create))

    @Common().exception_handler
    def get_all_extract(self) -> Response:
        """The active topics for the dropdown (names and ids only), already in the order admins set."""
        rows = [ContactAdminUtils.category_row(c) for c in ContactCategory.objects.filter(is_active=True).order_by('sort_order', 'name')]
        return Response(Utils.success_response_data(message=self.data_get, data={'data': rows}))
