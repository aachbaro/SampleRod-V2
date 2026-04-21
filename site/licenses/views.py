from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponseRedirect
from django.shortcuts import render
from django.utils.http import urlencode
from django.views.decorators.http import require_POST

from releases.artifacts import validate_release_dir
from releases.models import Release

from .models import License


def landing(request):
    current = Release.objects.filter(is_current=True).first()
    release_status = None
    if current:
        release_status = validate_release_dir(Path(settings.RELEASES_DIR) / "current", expected_version=current.version)
    active_license = None
    if request.user.is_authenticated:
        active_license = (
            License.objects.filter(user=request.user, paid_at__isnull=False, revoked_at__isnull=True)
            .first()
        )
    context = {
        "current_release": current,
        "download_available": bool(current and release_status and release_status.ok),
        "release_error": release_status.reason if current and release_status and not release_status.ok else "",
        "price_eur": settings.LICENSE_PRICE_CENTS / 100,
        "active_license": active_license,
    }
    return render(request, "landing.html", context)


@login_required
def account(request):
    licenses = License.objects.filter(user=request.user).order_by("-created_at")
    current = Release.objects.filter(is_current=True).first()
    release_status = None
    if current:
        release_status = validate_release_dir(Path(settings.RELEASES_DIR) / "current", expected_version=current.version)
    return render(
        request,
        "account.html",
        {
            "licenses": licenses,
            "current_release": current,
            "download_available": bool(current and release_status and release_status.ok),
            "release_error": release_status.reason if current and release_status and not release_status.ok else "",
            "setx_cmd_template": 'setx SAMPLEROD_UPDATE_FEED "{feed}"',
        },
    )


@login_required
@require_POST
def rotate_token(request, license_id: int):
    lic = License.objects.filter(pk=license_id, user=request.user).first()
    if not lic:
        raise Http404()
    lic.rotate_token()
    messages.success(
        request,
        "Token de mise à jour régénéré. L'ancien feed ne fonctionnera plus.",
    )
    return HttpResponseRedirect("/account")


@login_required
def download_setup(request):
    """
    Gated download of the current Setup.exe.

    The file is served from RELEASES_DIR/current/Setup.exe (symlink maintained
    by publish_release.ps1).
    """
    lic = (
        License.objects.filter(user=request.user, paid_at__isnull=False, revoked_at__isnull=True)
        .first()
    )
    if not lic:
        return HttpResponseRedirect("/?" + urlencode({"require": "license"}))

    current = Release.objects.filter(is_current=True).first()
    if not current:
        raise Http404("No release published yet")
    release_status = validate_release_dir(Path(settings.RELEASES_DIR) / "current", expected_version=current.version)
    if not release_status.ok:
        messages.error(
            request,
            "La release Windows actuellement publiee est invalide. "
            "Le telechargement est temporairement indisponible.",
        )
        return HttpResponseRedirect("/account")

    setup_path = Path(settings.RELEASES_DIR) / "current" / "Setup.exe"
    if not setup_path.exists():
        raise Http404("Setup.exe not on disk")

    resp = FileResponse(open(setup_path, "rb"), as_attachment=True, filename="SampleRodSetup.exe")
    return resp
