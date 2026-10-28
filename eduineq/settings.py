"""Django settings.

The system is an OPEN-ACCESS research portal: there is deliberately no login, no user accounts and no
roles (project decision).  Consequently ``django.contrib.auth``, ``admin`` and ``sessions`` are not
installed.  CSRF protection, secure headers, input validation and throttling remain in force.

Configuration comes from environment variables (never commit secrets):
  DJANGO_SECRET_KEY, DJANGO_DEBUG, DJANGO_ALLOWED_HOSTS, DJANGO_CSRF_TRUSTED_ORIGINS,
  DB_ENGINE (sqlite | mysql), DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT,
  ANALYSIS_EXECUTION (sync | thread), ANALYSIS_TIMEOUT_SECONDS, DJANGO_BEHIND_HTTPS
"""
import os
import sys
from pathlib import Path
# Load environment variables from .env or .env.example if present
_env_path = Path(__file__).resolve().parent.parent / ".env"
if not _env_path.is_file():
    _env_path = Path(__file__).resolve().parent.parent / ".env.example"
if _env_path.is_file():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except ImportError:
        pass  # dotenv not installed; rely on OS environment variables

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


DEBUG = env_bool("DJANGO_DEBUG", True)
TESTING = "pytest" in sys.modules or "test" in sys.argv

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    # Use an insecure key for development if not set
    SECRET_KEY = "dev-secret-key-override-1234567890"

_allowed_raw = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()]
if DEBUG or TESTING:
    # Always allow local dev hosts, regardless of any OS-level env var overrides
    _allowed_raw = list(dict.fromkeys(_allowed_raw + ["127.0.0.1", "localhost", "testserver"]))
ALLOWED_HOSTS = _allowed_raw
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "portal",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "portal.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "eduineq.urls"
WSGI_APPLICATION = "eduineq.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "portal.context_processors.site",
    ]},
}]

# ---- database -------------------------------------------------------------------------------------------------
DB_ENGINE = os.environ.get("DB_ENGINE", "sqlite").lower()
if DB_ENGINE == "mysql":
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("DB_NAME", "eduineq"),
        "USER": os.environ.get("DB_USER", ""),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DB_PORT", "3306"),
        "OPTIONS": {"charset": "utf8mb4", "init_command": "SET sql_mode='STRICT_TRANS_TABLES'"},
        "CONN_MAX_AGE": 60,
    }}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": os.environ.get("SQLITE_PATH", str(BASE_DIR / "db.sqlite3"))}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Africa/Lagos"
USE_I18N = False
USE_TZ = True

# ---- static files ----------------------------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage" if not TESTING else "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# ---- security ------------------------------------------------------------------------------------------------------
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
CSRF_COOKIE_HTTPONLY = False  # the CSRF cookie is read by forms only; no JS reads it
CSRF_COOKIE_SAMESITE = "Lax"
# Never enforce HTTPS in debug/test mode — OS-level env vars may still say DJANGO_BEHIND_HTTPS=1
BEHIND_HTTPS = False if (DEBUG or TESTING) else env_bool("DJANGO_BEHIND_HTTPS", True)
if BEHIND_HTTPS:
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", True)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = False
    CSRF_COOKIE_SECURE = True
DATA_UPLOAD_MAX_MEMORY_SIZE = 1_000_000

# ---- project-specific ---------------------------------------------------------------------------------------------
DATA_DIR = BASE_DIR / "data"
ARTEFACT_DIR = Path(os.environ.get("ARTEFACT_DIR", BASE_DIR / "artefacts"))
REPORT_DIR = BASE_DIR / "reports"
ANALYSIS_EXECUTION = os.environ.get("ANALYSIS_EXECUTION", "sync")          # sync | thread
ANALYSIS_TIMEOUT_SECONDS = int(os.environ.get("ANALYSIS_TIMEOUT_SECONDS", "900"))
ANALYSIS_MAX_RETRIES = int(os.environ.get("ANALYSIS_MAX_RETRIES", "2"))
# Open site => protect the expensive endpoints from abuse (per client, per window)
THROTTLE_RUNS_PER_HOUR = int(os.environ.get("THROTTLE_RUNS_PER_HOUR", "30"))
MAX_SAVED_SCENARIOS = int(os.environ.get("MAX_SAVED_SCENARIOS", "500"))
IP_HASH_SALT = os.environ.get("IP_HASH_SALT", SECRET_KEY)
# Behind nginx every request arrives from the proxy; enable this ONLY when the proxy sets X-Real-IP (deploy/nginx.conf does)
TRUST_PROXY_HEADERS = env_bool("DJANGO_TRUST_PROXY_HEADERS", False)

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "eduineq"}}

LOGGING = {
    "version": 1, "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "std"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
