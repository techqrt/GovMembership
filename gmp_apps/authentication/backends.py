from typing import Any

from django.contrib.auth.backends import ModelBackend
from django.db.models import Q
from django.http import HttpRequest

from gmp_apps.authentication.models import User


class AdminSiteBackend(ModelBackend):
    """Admin-site login with membership ID or email. Staff accounts only: ordinary members can
    never obtain an admin session through this backend (the API uses JWT, not sessions)."""

    def authenticate(self, request: HttpRequest | None, username: str | None = None, password: str | None = None, **kwargs: Any) -> User | None:
        username = username or kwargs.get(User.USERNAME_FIELD)
        if not username or password is None:
            return None
        username = username.strip()
        user = User.objects.filter(Q(membership_id=username.upper()) | Q(email=username.lower())).first()
        if user and user.is_staff and user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
