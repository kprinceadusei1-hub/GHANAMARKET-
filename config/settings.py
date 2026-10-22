import os
import warnings
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() == "true"
# Render sets this to the service's public hostname (e.g. ghanamarket.onrender.com).
RENDER_HOST = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
if not DEBUG:
    if SECRET_KEY in {"dev-only-change-me", "replace-this-for-local-development"} or len(SECRET_KEY) < 50:
        raise ImproperlyConfigured("Set DJANGO_SECRET_KEY to a unique secret of at least 50 characters when DEBUG is false.")
    if not os.getenv("DJANGO_ALLOWED_HOSTS", "").strip() and not RENDER_HOST:
        raise ImproperlyConfigured("Set DJANGO_ALLOWED_HOSTS explicitly when DEBUG is false.")
ALLOWED_HOSTS = [host.strip() for host in os.getenv(
    "DJANGO_ALLOWED_HOSTS", "" if RENDER_HOST else "127.0.0.1,localhost"
).split(",") if host.strip()]
if RENDER_HOST:
    ALLOWED_HOSTS.append(RENDER_HOST)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "marketplace",
    "commerce",
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
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "marketplace.context_processors.admin_dashboard",
        "marketplace.context_processors.marketplace_nav",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
def postgres_database_config(database_url):
    """Parse a PostgreSQL URL without silently changing database backends."""
    try:
        parsed = urlsplit(database_url)
        port = parsed.port
    except ValueError as exc:
        raise ImproperlyConfigured("DATABASE_URL contains an invalid PostgreSQL URL.") from exc

    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ImproperlyConfigured("DATABASE_URL must use postgres:// or postgresql://.")
    database_name = unquote(parsed.path.lstrip("/"))
    if not parsed.hostname or not database_name:
        raise ImproperlyConfigured("PostgreSQL DATABASE_URL must include a host and database name.")

    options = {}
    supported_options = {"sslmode", "application_name", "options", "connect_timeout", "target_session_attrs"}
    for key, values in parse_qs(parsed.query, keep_blank_values=False).items():
        if key not in supported_options:
            raise ImproperlyConfigured(f"Unsupported PostgreSQL DATABASE_URL option: {key}")
        options[key] = values[-1]

    config = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": database_name,
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname,
        "PORT": str(port or ""),
        "CONN_MAX_AGE": 600,
    }
    if options:
        config["OPTIONS"] = options
    return config


if DATABASE_URL.startswith(("postgres://", "postgresql://")):
    DATABASES = {"default": postgres_database_config(DATABASE_URL)}
elif DATABASE_URL:
    raise ImproperlyConfigured("DATABASE_URL must use a supported PostgreSQL URL or be empty for SQLite.")
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
TIME_ZONE = "Africa/Accra"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
# WhiteNoise warns when STATIC_ROOT does not exist yet (normal before `collectstatic`, e.g. in development).
warnings.filterwarnings("ignore", message="No directory at: ")
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DEFAULT_COUNTRY = os.getenv("DEFAULT_COUNTRY", "GH")
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "GHS")
AUTH_USER_MODEL = "marketplace.User"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "home"

PASSWORD_RESET_TIMEOUT = 60 * 60 * 24 * 3

# Email: console output in development; SMTP settings come from the environment in production.
EMAIL_BACKEND = os.getenv(
    "DJANGO_EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True").lower() == "true"
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "GhanaMarket <no-reply@localhost>")

# Shared cache backs rate limits; set REDIS_URL in production so limits apply across workers.
REDIS_URL = os.getenv("REDIS_URL", "").strip()
if REDIS_URL:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}}
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# Upload limits: listing photos are validated to 5 MB each; cap the whole request too.
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FILES = 10

SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if origin.strip()]
if RENDER_HOST:
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_HOST}")
# Only enable when the app runs behind a proxy that sets/overwrites these headers.
TRUST_X_FORWARDED_FOR = os.getenv("DJANGO_TRUST_X_FORWARDED_FOR", "False").lower() == "true"
if os.getenv("DJANGO_SECURE_PROXY_SSL_HEADER", "False").lower() == "true":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if not DEBUG:
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_SSL_REDIRECT = os.getenv("DJANGO_SECURE_SSL_REDIRECT", "True").lower() == "true"
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    X_FRAME_OPTIONS = "DENY"
    # HSTS is opt-in: only enable once the domain (and subdomains, if included) are HTTPS-only.
    SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "0"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", "False").lower() == "true"
    SECURE_HSTS_PRELOAD = os.getenv("DJANGO_SECURE_HSTS_PRELOAD", "False").lower() == "true"
    if not EMAIL_HOST and EMAIL_BACKEND.endswith("smtp.EmailBackend"):
        raise ImproperlyConfigured("Set EMAIL_HOST (and credentials) so password reset emails can be delivered.")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": os.getenv("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {"django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False}},
}

TEST_RUNNER = "config.test_runner.IsolatedMediaTestRunner"

# ---- Commerce -------------------------------------------------------------------------------
# PAYMENT_PROVIDER: "paystack", "test" (DEBUG only, no real money) or "" to disable online payment.
PAYMENT_PROVIDER = os.getenv("PAYMENT_PROVIDER", "test" if DEBUG else "").strip().lower()
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "").strip()
if PAYMENT_PROVIDER == "test" and not DEBUG:
    raise ImproperlyConfigured("PAYMENT_PROVIDER=test is only allowed in development (DEBUG=True).")
if PAYMENT_PROVIDER == "paystack" and not PAYSTACK_SECRET_KEY:
    raise ImproperlyConfigured("Set PAYSTACK_SECRET_KEY when PAYMENT_PROVIDER=paystack.")
CHECKOUT_EXPIRY_MINUTES = int(os.getenv("CHECKOUT_EXPIRY_MINUTES", "60"))
# Absolute base URL used in emails, e.g. https://ghanamarket.example
SITE_URL = os.getenv("SITE_URL", "http://127.0.0.1:8000" if DEBUG else (f"https://{RENDER_HOST}" if RENDER_HOST else "")).strip()
NOTIFICATION_EMAILS_ENABLED = os.getenv("NOTIFICATION_EMAILS_ENABLED", "True").lower() == "true"

# Identity documents for seller verification live outside MEDIA_ROOT and are only served to staff.
PRIVATE_MEDIA_ROOT = Path(os.getenv("PRIVATE_MEDIA_ROOT", BASE_DIR / "private_media"))
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "").strip()

# Cloud storage for uploads: any S3-compatible service (Cloudflare R2, AWS S3, Backblaze B2...).
# Listing photos go to MEDIA_S3_BUCKET (publicly readable); identity documents go to the separate,
# private PRIVATE_S3_BUCKET and are only ever streamed to staff by the app. Keys come from the
# environment only. Hosts with temporary disks (like Render) must use this, or uploads are lost.
MEDIA_S3_BUCKET = os.getenv("MEDIA_S3_BUCKET", "").strip()
PRIVATE_S3_BUCKET = os.getenv("PRIVATE_S3_BUCKET", "").strip()
S3_CONNECTION = {
    "endpoint_url": os.getenv("S3_ENDPOINT_URL", "").strip() or None,
    "access_key": os.getenv("S3_ACCESS_KEY_ID", "").strip(),
    "secret_key": os.getenv("S3_SECRET_ACCESS_KEY", "").strip(),
    "region_name": os.getenv("S3_REGION", "auto").strip(),
    "signature_version": "s3v4",
    "file_overwrite": False,
    "default_acl": None,
}
# Public hostname that serves the media bucket, e.g. pub-xxxx.r2.dev or media.ghanamarket.com.
MEDIA_PUBLIC_DOMAIN = os.getenv("MEDIA_PUBLIC_DOMAIN", "").strip().removeprefix("https://").rstrip("/")
if MEDIA_S3_BUCKET and not PRIVATE_S3_BUCKET:
    raise ImproperlyConfigured("Set PRIVATE_S3_BUCKET too, so identity documents are kept off the server's temporary disk.")
if not DEBUG and os.getenv("RENDER") and not MEDIA_S3_BUCKET:
    raise ImproperlyConfigured("Render's disk is wiped on every deploy: set MEDIA_S3_BUCKET and PRIVATE_S3_BUCKET.")

# Production: compressed, hashed static files (cache-busting) served by WhiteNoise after `collectstatic`.
if not DEBUG:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
    if MEDIA_S3_BUCKET:
        STORAGES["default"] = {"BACKEND": "storages.backends.s3.S3Storage", "OPTIONS": {
            **S3_CONNECTION, "bucket_name": MEDIA_S3_BUCKET,
            "custom_domain": MEDIA_PUBLIC_DOMAIN or None, "querystring_auth": not MEDIA_PUBLIC_DOMAIN,
        }}
