"""
Django settings for the Traffic & Accident Management System (TAMS).

All secrets / deploy-specific values come from environment variables (optionally
loaded from a local `.env` file). Defaults are safe for local development only.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "dev-insecure-key-change-me-in-production-0123456789"
)
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.LazyExpiryMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.tams",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# SQLite for development. Production recommendation: PostgreSQL (see NOTES.md).
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("SQLITE_PATH", str(BASE_DIR / "db.sqlite3")),
    }
}

AUTH_USER_MODEL = "core.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "home"

# --- Domain configuration (all overridable via env) -------------------------
TAMS = {
    # Minutes an incident stays "fresh" without a new still_active confirmation.
    "INCIDENT_FRESHNESS_MINUTES": env_int("TAMS_INCIDENT_FRESHNESS_MINUTES", 60),
    # Reputation-weighted confirmation score required to auto-verify an incident.
    "VERIFICATION_THRESHOLD": env_int("TAMS_VERIFICATION_THRESHOLD", 3),
    # Weighted "cleared" score at which a non-assigned incident is auto-marked stale.
    "CLEARED_THRESHOLD": env_int("TAMS_CLEARED_THRESHOLD", 3),
    # Reputation bounds and deltas.
    "REPUTATION_START": 10,
    "REPUTATION_TRUSTED": 20,  # >= this: confirmation counts double
    "REPUTATION_LOW": 5,  # < this: confirmation counts zero (shadow-weighted)
    "REPUTATION_MATCH_DELTA": 1,
    "REPUTATION_MISMATCH_DELTA": -1,
    "REPUTATION_FALSE_REPORT_DELTA": -3,
    "REPUTATION_GOOD_REPORT_DELTA": 2,
    # Seconds between lazy expiry sweeps triggered by web requests.
    "EXPIRY_SWEEP_INTERVAL_SECONDS": env_int("TAMS_EXPIRY_SWEEP_INTERVAL_SECONDS", 60),
    # Notification poll interval used by the frontend (ms).
    "NOTIFICATION_POLL_MS": env_int("TAMS_NOTIFICATION_POLL_MS", 30000),
    # Distance (m) from a saved route within which a blockage counts as "on route".
    "ROUTE_BUFFER_M": env_int("TAMS_ROUTE_BUFFER_M", 300),
    # Default radius (km) for "nearby" incidents on the citizen dashboard.
    "NEARBY_RADIUS_KM": env_int("TAMS_NEARBY_RADIUS_KM", 10),
}

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
