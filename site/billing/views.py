import logging
from pathlib import Path

import stripe
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from licenses.models import License
from releases.artifacts import validate_release_dir
from releases.models import Release


logger = logging.getLogger(__name__)


def _stripe():
    if not settings.STRIPE_SECRET_KEY:
        raise RuntimeError("STRIPE_SECRET_KEY is not set")
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


@login_required
@require_POST
def create_checkout_session(request):
    if not settings.STRIPE_PRICE_ID:
        return HttpResponseBadRequest("STRIPE_PRICE_ID not configured")

    s = _stripe()
    try:
        session = s.checkout.Session.create(
            mode="payment",
            line_items=[{"price": settings.STRIPE_PRICE_ID, "quantity": 1}],
            client_reference_id=str(request.user.oidc_sub),
            customer_email=request.user.email or None,
            success_url=f"{settings.SITE_URL}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{settings.SITE_URL}/checkout/cancel",
            locale="fr",
            metadata={"user_id": str(request.user.pk)},
        )
    except stripe.error.StripeError as exc:
        logger.exception("Stripe checkout creation failed")
        return HttpResponseBadRequest(f"Stripe error: {exc}")

    return redirect(session.url, permanent=False)


@login_required
def success(request):
    session_id = request.GET.get("session_id")
    lic = None
    if session_id:
        lic = License.objects.filter(
            stripe_session_id=session_id, user=request.user
        ).first()
    current = Release.objects.filter(is_current=True).first()
    release_status = None
    if current:
        release_status = validate_release_dir(
            Path(settings.RELEASES_DIR) / "current",
            expected_version=current.version,
        )
    return render(
        request,
        "checkout_success.html",
        {
            "license": lic,
            "session_id": session_id,
            "download_available": bool(current and release_status and release_status.ok),
            "release_error": release_status.reason if current and release_status and not release_status.ok else "",
        },
    )


def cancel(request):
    return render(request, "checkout_cancel.html")


@csrf_exempt
def stripe_webhook(request):
    try:
        return _stripe_webhook_inner(request)
    except Exception:
        logger.exception("Unhandled error in stripe_webhook")
        return HttpResponse(status=500, content="internal error (logged)")


def _stripe_webhook_inner(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    secret = settings.STRIPE_WEBHOOK_SECRET
    if not secret:
        logger.error("STRIPE_WEBHOOK_SECRET not configured")
        return HttpResponse(status=500, content="STRIPE_WEBHOOK_SECRET not configured")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except ValueError:
        logger.warning("Stripe webhook: invalid payload")
        return HttpResponseBadRequest("Invalid payload")
    except Exception as exc:
        # Stripe SDK 15+ exposes SignatureVerificationError at the top level
        # (stripe.SignatureVerificationError). Earlier versions used
        # stripe.error.SignatureVerificationError. Catch broadly here but
        # distinguish sig-verify failures vs. real bugs via the class name.
        name = type(exc).__name__
        if name == "SignatureVerificationError":
            logger.warning("Stripe webhook: bad signature (%s)", exc)
            return HttpResponseBadRequest("Invalid signature")
        raise

    et = event["type"]
    obj = event["data"]["object"]

    if et == "checkout.session.completed":
        _handle_checkout_completed(obj)
    elif et == "payment_intent.payment_failed":
        logger.warning("Stripe payment failed: %s", obj.get("id"))
    else:
        logger.info("Unhandled stripe event: %s", et)

    return JsonResponse({"ok": True})


def _handle_checkout_completed(session: dict):
    from users.models import User

    session_id = session["id"]
    if License.objects.filter(stripe_session_id=session_id).exists():
        return  # already processed; idempotency

    client_ref = session.get("client_reference_id") or ""
    user = None
    if client_ref:
        user = User.objects.filter(oidc_sub=client_ref).first()
    if not user and session.get("customer_email"):
        user = User.objects.filter(email=session["customer_email"]).first()
    if not user:
        logger.error(
            "Stripe checkout completed but no matching user (ref=%s)", client_ref
        )
        return

    License.objects.create(
        user=user,
        stripe_session_id=session_id,
        stripe_payment_intent=session.get("payment_intent") or "",
        amount_paid_cents=session.get("amount_total") or settings.LICENSE_PRICE_CENTS,
        currency=(session.get("currency") or settings.LICENSE_CURRENCY).lower(),
        paid_at=timezone.now(),
    )
    logger.info("License granted to %s via session %s", user, session_id)
