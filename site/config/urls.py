from django.contrib import admin
from django.urls import include, path

from licenses import views as license_views


urlpatterns = [
    path("", license_views.landing, name="landing"),
    path("account", license_views.account, name="account"),
    path("account/license/<int:license_id>/rotate-token", license_views.rotate_token, name="rotate_token"),
    path("download", license_views.download_setup, name="download_setup"),
    path("auth/", include("users.urls")),
    path("checkout/", include("billing.urls")),
    path("webhooks/", include("billing.webhooks_urls")),
    path("releases/", include("releases.urls")),
    path("api/", include("releases.api_urls")),
    path("admin/", admin.site.urls),
]
