from typing import Any

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed


class VersionedJWTAuthentication(JWTAuthentication):
    """JWT login that also checks the token's `token_version` against the user's current one.

    The version changes whenever an admin suspends or reactivates the account, so tokens issued
    before that moment stop working at once (an access token cannot be blacklisted). Tokens issued
    before this field existed carry no version and count as version 0."""

    def get_user(self, validated_token: Any) -> Any:
        user = super().get_user(validated_token)
        if validated_token.get('token_version', 0) != user.token_version:
            raise AuthenticationFailed('Token is no longer valid', code='token_not_valid')
        return user


from drf_spectacular.extensions import OpenApiAuthenticationExtension
from drf_spectacular.plumbing import build_bearer_security_scheme_object


class VersionedJWTScheme(OpenApiAuthenticationExtension):
    """Documents the custom class in swagger exactly like the stock JWT one (a Bearer token)."""

    target_class = 'gmp_apps.authentication.jwt.VersionedJWTAuthentication'
    name = 'jwtAuth'

    def get_security_definition(self, auto_schema: object) -> dict:
        return build_bearer_security_scheme_object(header_name='Authorization', token_prefix='Bearer', bearer_format='JWT')
