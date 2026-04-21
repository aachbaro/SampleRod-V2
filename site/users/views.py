from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import login, logout
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect

from .models import User
from .oidc import get_oauth_client


def _next_url(request) -> str:
    nxt = request.GET.get("next") or request.POST.get("next") or "/account"
    # Only allow relative paths
    if not nxt.startswith("/"):
        nxt = "/account"
    return nxt


def login_view(request):
    client = get_oauth_client()
    request.session["post_login_next"] = _next_url(request)
    return client.authorize_redirect(request, settings.OIDC_REDIRECT_URI)


def callback_view(request):
    client = get_oauth_client()
    try:
        token = client.authorize_access_token(request)
    except Exception as exc:  # pragma: no cover - surface auth errors verbatim
        return HttpResponseBadRequest(f"OIDC callback error: {exc}")

    claims = token.get("userinfo")
    if not claims:
        # Fallback to userinfo endpoint if the token didn't embed the id_token claims
        claims = client.userinfo(token=token)

    try:
        user = User.from_oidc_claims(claims)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    nxt = request.session.pop("post_login_next", "/account")
    return redirect(nxt)


def logout_view(request):
    logout(request)
    params = urlencode(
        {"post_logout_redirect_uri": settings.OIDC_POST_LOGOUT_REDIRECT_URI}
    )
    # auth-server Django logout endpoint; ignored gracefully if issuer doesn't expose it
    return redirect(settings.OIDC_ISSUER.rstrip("/") + "/logout/?" + params)
