"""Projects Gateway settings.

Every deployment-specific value comes from the environment, i.e. the repo-root `.env`
(see `.env.example`). Nothing secret lives in this file.
"""
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent      # backend/
REPO_DIR = BASE_DIR.parent                              # projects_gateway/
try:
    load_dotenv(REPO_DIR / '.env')
except PermissionError:
    # The .env may be readable by its owner only (600). Another account running the tests
    # goes on without it: DJANGO_DEBUG=True and a DATA_DIR of its own.
    pass


def env_list(name, default=''):
    return [v.strip() for v in os.environ.get(name, default).split(',') if v.strip()]


def env_datetime(name):
    """An ISO 8601 date and time with its UTC offset, or None (unset, unreadable or no offset)."""
    try:
        value = datetime.fromisoformat(os.environ.get(name, '').strip())
    except ValueError:
        return None
    return value if value.tzinfo else None


DEBUG = os.environ.get('DJANGO_DEBUG', 'False') == 'True'

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '')
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError('DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is not True')
    SECRET_KEY = 'dev-only-insecure-key'

ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1')

# Behind host nginx (TLS terminated there).
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
if not DEBUG:
    SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'True') == 'True'
    SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '0'))
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'django_filters',
    'accounts',
    'catalog',
    'monitoring',
    'backups',
    'domains',
]
# The Django admin uses its own password login, separate from the auth server:
# available in development only, never exposed in production.
if DEBUG:
    INSTALLED_APPS.insert(0, 'django.contrib.admin')

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'gateway.urls'
WSGI_APPLICATION = 'gateway.wsgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

DATA_DIR = Path(os.environ.get('DATA_DIR', REPO_DIR / 'data'))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': DATA_DIR / 'gateway.sqlite3',
        # Two processes write (app + worker): WAL lets reads go on during a write, and
        # IMMEDIATE + a timeout make writers wait for each other instead of failing.
        'OPTIONS': {
            'init_command': 'PRAGMA journal_mode=WAL;',
            'transaction_mode': 'IMMEDIATE',
            'timeout': 20,
        },
    }
}

CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Europe/Rome'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
# No STATIC_ROOT / collectstatic: production has no admin and the API renders JSON only,
# so no Django static files are served (WhiteNoise would warn about an empty folder).

# The built Vue app. WhiteNoise serves its files at the site root, and
# gateway.views.spa_index answers every other non-API route with its index.html.
FRONTEND_DIST = Path(os.environ.get('FRONTEND_DIST', REPO_DIR / 'frontend' / 'dist'))
WHITENOISE_ROOT = FRONTEND_DIST if FRONTEND_DIST.is_dir() else None
# The PWA manifest: WhiteNoise doesn't know the extension (it would send octet-stream).
WHITENOISE_MIMETYPES = {'.webmanifest': 'application/manifest+json'}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['accounts.authentication.RemoteOAuth2Authentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
}

# Login: any OpenID Connect provider, Authorization Code + PKCE in the frontend with a public
# client (no secret). The endpoints come from OIDC_ISSUER's discovery document (accounts/oidc.py);
# every API request's Bearer token is checked at its userinfo endpoint. OIDC_USERNAME_CLAIM is the
# claim matched against the users added with add_user, at each one's first login. Unset issuer
# or client: nobody gets in.
OIDC_ISSUER = os.environ.get('OIDC_ISSUER', '')
OIDC_CLIENT_ID = os.environ.get('OIDC_CLIENT_ID', '')
OIDC_USERNAME_CLAIM = os.environ.get('OIDC_USERNAME_CLAIM', '') or 'preferred_username'

# Read-only fine-grained token for the GitHub sync (repos under GITHUB_OWNER only).
GITHUB_OWNER = os.environ.get('GITHUB_OWNER', '')
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')

# Live status (the worker): how often every public URL is checked.
HEALTH_CHECK_MINUTES = float(os.environ.get('HEALTH_CHECK_MINUTES') or 15)
# The host's local scan (deploy/scan_local.py, from the crontab): its snapshot, and the
# catalog platform it describes.
SCAN_FILE = DATA_DIR / 'scan.json'
SCAN_PLATFORM = os.environ.get('SCAN_PLATFORM', 'home-server')
# Security alerts from that scan (monitoring/local.py, security_attention). SSH_KNOWN_KEYS: the
# keys allowed to log in, as `ssh-keygen -lf` prints them (SHA256:…); any other key found in an
# authorized_keys file, or used to log in, is red. SECURITY_SINCE: events before this moment
# are ignored (ISO 8601 with its offset), e.g. the traces of an incident already dealt with.
SSH_KNOWN_KEYS = env_list('SSH_KNOWN_KEYS')
SECURITY_SINCE = env_datetime('SECURITY_SINCE')
# The app's public address, for the links in notifications ('' = no link).
SITE_URL = os.environ.get('SITE_URL', '').rstrip('/')

# Notifications: a message when something in "Needs attention" turns red, and when it
# clears, through every channel configured here (none: nothing is sent).
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
NOTIFY_EMAIL_TO = env_list('NOTIFY_EMAIL_TO')
# (`or`: a setting present in .env but left empty means the default.)
EMAIL_HOST = os.environ.get('EMAIL_HOST') or 'localhost'
EMAIL_PORT = int(os.environ.get('EMAIL_PORT') or 465)
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_SSL = EMAIL_PORT == 465          # 587 is STARTTLS
EMAIL_USE_TLS = EMAIL_PORT == 587
EMAIL_TIMEOUT = 20
DEFAULT_FROM_EMAIL = f'Projects Gateway <{EMAIL_HOST_USER}>' if EMAIL_HOST_USER else 'webmaster@localhost'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': os.environ.get('LOG_LEVEL', 'INFO')},
}
