from django.urls import path

from . import views


urlpatterns = [
    path("create-session", views.create_checkout_session, name="create_checkout_session"),
    path("success", views.success, name="checkout_success"),
    path("cancel", views.cancel, name="checkout_cancel"),
]
