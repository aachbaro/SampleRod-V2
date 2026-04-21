from django.contrib import admin

from .models import License


@admin.register(License)
class LicenseAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "paid_at",
        "revoked_at",
        "amount_paid_cents",
        "currency",
        "stripe_session_id",
    )
    search_fields = ("user__email", "stripe_session_id", "stripe_payment_intent")
    readonly_fields = ("update_token", "created_at")
