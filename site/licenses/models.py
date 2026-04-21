import secrets

from django.conf import settings
from django.db import models


def _new_token() -> str:
    return secrets.token_urlsafe(32)


class License(models.Model):
    """
    One row per successful Stripe checkout.

    Marks a user as licensed for SampleRod and carries the secret
    `update_token` baked into their Squirrel feed URL.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="licenses"
    )
    stripe_session_id = models.CharField(max_length=255, unique=True)
    stripe_payment_intent = models.CharField(max_length=255, blank=True)
    amount_paid_cents = models.IntegerField()
    currency = models.CharField(max_length=8)
    update_token = models.CharField(max_length=64, unique=True, default=_new_token)
    paid_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"License({self.user}, paid={'yes' if self.paid_at else 'no'})"

    @property
    def is_active(self) -> bool:
        return bool(self.paid_at and not self.revoked_at)

    def rotate_token(self) -> str:
        self.update_token = _new_token()
        self.save(update_fields=["update_token"])
        return self.update_token

    def feed_url(self) -> str:
        return f"{settings.SITE_URL.rstrip('/')}/releases/{self.update_token}/"
