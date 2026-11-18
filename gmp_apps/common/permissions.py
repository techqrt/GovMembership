from rest_framework.permissions import BasePermission
from rest_framework.request import Request


class IsMemberRole(BasePermission):
    """Active user with the member role. Admin work happens in the Unfold admin site, not here."""

    def has_permission(self, request: Request, view: object) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and user.role == 'member')


def has_admin_permission(codename: str) -> type[BasePermission]:
    """Permission class for an admin-only REST action: active admin-role user holding a specific
    Django permission (e.g. 'schemes.delete_scheme'), granted through groups by a superuser."""

    class HasAdminPermission(BasePermission):
        def has_permission(self, request: Request, view: object) -> bool:
            user = request.user
            return bool(
                user and user.is_authenticated and user.is_active and user.role == 'admin' and user.has_perm(codename)
            )

    HasAdminPermission.__name__ = f'HasAdminPermission_{codename.replace(".", "_")}'
    return HasAdminPermission
