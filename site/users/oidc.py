"""
Thin wrapper around Authlib's OAuth client to talk to auth.pascuans.dev.

The auth-server exposes standard OIDC endpoints; we rely on discovery.
"""
from authlib.integrations.django_client import OAuth

from django.conf import settings


_oauth = OAuth()


def get_oauth_client():
    """Lazy-register the pascuans OIDC client and return it."""
    if "pascuans" not in _oauth._registry:
        _oauth.register(
            name="pascuans",
            server_metadata_url=settings.OIDC_ISSUER.rstrip("/") + "/.well-known/openid-configuration",
            client_id=settings.OIDC_CLIENT_ID,
            client_secret=settings.OIDC_CLIENT_SECRET,
            client_kwargs={
                "scope": settings.OIDC_SCOPES,
            },
        )
    return _oauth.create_client("pascuans")
