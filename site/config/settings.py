"""
Django settings for samplerod.pascuans.dev site.

Kept deliberately small — one Django project, four local apps
(users, licenses, billing, releases), SQLite in a mounted volume in prod.
"""
from pathlib import Path

import environ


BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    OIDC_ENABLE_REFRESH_TOKENS=(bool, False),
    STRIPE_LIVE=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")


SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-dev-key-change-me")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["127.0.0.1", "localhost"])
CSRF_TRUSTED_ORIGINS = env.list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    default=["http://127.0.0.1:8003", "http://localhost:8003"],
)

SITE_URL = env("SITE_URL", default="http://127.0.0.1:8003")

# --- Apps --------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "users",
    "licenses",
    "billing",
    "releases",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "config.context.site_url",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Database ----------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": env("DJANGO_DB_PATH", default=str(BASE_DIR / "data" / "samplerod-site.sqlite3")),
    }
}

# --- Auth --------------------------------------------------------------

AUTH_USER_MODEL = "users.User"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
]

LOGIN_URL = "/auth/login"
LOGIN_REDIRECT_URL = "/account"
LOGOUT_REDIRECT_URL = "/"

# --- OIDC (pascuans auth-server) --------------------------------------

OIDC_ISSUER = env("OIDC_ISSUER", default="https://auth.pascuans.dev")
OIDC_CLIENT_ID = env("OIDC_CLIENT_ID", default="samplerod-web")
OIDC_CLIENT_SECRET = env("OIDC_CLIENT_SECRET", default="")
OIDC_REDIRECT_URI = env(
    "OIDC_REDIRECT_URI", default=f"{SITE_URL}/auth/callback"
)
OIDC_POST_LOGOUT_REDIRECT_URI = env(
    "OIDC_POST_LOGOUT_REDIRECT_URI", default=SITE_URL + "/"
)
OIDC_SCOPES = env("OIDC_SCOPES", default="openid profile email")

# --- Stripe ------------------------------------------------------------

STRIPE_PUBLIC_KEY = env("STRIPE_PUBLIC_KEY", default="")
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")
STRIPE_PRICE_ID = env("STRIPE_PRICE_ID", default="")
STRIPE_LIVE = env("STRIPE_LIVE")

LICENSE_PRICE_CENTS = 2500
LICENSE_CURRENCY = "eur"

# --- Releases ----------------------------------------------------------

RELEASES_DIR = Path(env("RELEASES_DIR", default=str(BASE_DIR / "releases-dev")))
SAMPLEROD_ADMIN_TOKEN = env("SAMPLEROD_ADMIN_TOKEN", default="")

# --- i18n / tz ---------------------------------------------------------

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True

# --- Static ------------------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Security for prod -------------------------------------------------

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
