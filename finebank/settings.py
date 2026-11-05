"""Pengaturan FineBank (Django). Konfigurasi sensitif dibaca dari environment / .env."""
import os
from datetime import timedelta
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file():
    f = BASE_DIR / '.env'
    if f.exists():
        for line in f.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env_file()

TESTING = 'test' in os.sys.argv
DEBUG = os.environ.get('DEBUG', 'true').lower() == 'true'
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-only-ganti-di-produksi-minimal-32-karakter')
if not DEBUG and SECRET_KEY == 'dev-only-ganti-di-produksi-minimal-32-karakter':
    raise RuntimeError('Set SECRET_KEY di environment untuk produksi')
ALLOWED_HOSTS = [h.strip() for h in os.environ.get('ALLOWED_HOSTS', '*').split(',') if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',') if o.strip()]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'drf_spectacular',
    'corsheaders',
    'silk',
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'silk.middleware.SilkyMiddleware',  # profiling request + query ORM (materi 7)
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'finebank.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]
WSGI_APPLICATION = 'finebank.wsgi.application'

# Database: PostgreSQL lewat DATABASE_URL (Docker / Neon); jika kosong -> SQLite lokal.
# Saat menjalankan test, selalu SQLite in-memory (tidak pernah menyentuh database sungguhan).
_db_url = os.environ.get('DATABASE_URL', '')
if _db_url and not TESTING:
    DATABASES = {'default': dj_database_url.parse(_db_url, conn_max_age=60)}
else:
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}

AUTH_USER_MODEL = 'core.User'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
]

LANGUAGE_CODE = 'id'
TIME_ZONE = 'Asia/Jakarta'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Proxy (Render, Vercel, Docker di belakang nginx) meneruskan skema HTTPS
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# CORS: izinkan frontend FineBank Admin UI
_cors = os.environ.get('CORS_ORIGINS', '*')
if _cors == '*':
    CORS_ALLOW_ALL_ORIGINS = True
else:
    CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors.split(',') if o.strip()]

# ---- Django REST Framework ----
RATE_WINDOW_SECONDS = 15 * 60
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['core.auth.JWTAuth'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_RENDERER_CLASSES': ['core.renderers.EnvelopeRenderer'],
    'DEFAULT_PARSER_CLASSES': ['rest_framework.parsers.JSONParser'],
    'EXCEPTION_HANDLER': 'core.exceptions.handler',
    'DEFAULT_PAGINATION_CLASS': 'core.pagination.StandardPagination',
    'COERCE_DECIMAL_TO_STRING': False,
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    # Throttling: 100 request / 15 menit per IP untuk /api; login & register 10 / 15 menit
    'DEFAULT_THROTTLE_CLASSES': ['core.throttles.GlobalThrottle'],
    'DEFAULT_THROTTLE_RATES': {
        'global': int(os.environ.get('RATE_LIMIT_MAX', 100)),
        'auth': int(os.environ.get('RATE_LIMIT_AUTH_MAX', 10)),
    },
}
JWT_LIFETIME = timedelta(days=1)

SPECTACULAR_SETTINGS = {
    'TITLE': 'FineBank API (Django)',
    'DESCRIPTION': 'Backend REST API untuk FineBank Admin UI: auth JWT, pengeluaran, kategori, tagihan, statistik.',
    'VERSION': '2.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'SECURITY': [{'bearerAuth': []}],
    'APPEND_COMPONENTS': {'securitySchemes': {'bearerAuth': {'type': 'http', 'scheme': 'bearer', 'bearerFormat': 'JWT'}}},
}

# ---- django-silk: profiling (hanya staff/admin) ----
SILKY_PYTHON_PROFILER = False
SILKY_AUTHENTICATION = True
SILKY_AUTHORISATION = True
SILKY_PERMISSIONS = lambda user: user.is_staff  # noqa: E731
SILKY_MAX_RECORDED_REQUESTS = 2000
SILKY_META = True
SILKY_IGNORE_PATHS = []


if TESTING:  # silk menulis query sendiri; matikan agar assertNumQueries & test cepat
    MIDDLEWARE = [m for m in MIDDLEWARE if 'silk' not in m]

# Silk memakai login sesi Django: arahkan ke halaman login admin (bukan /accounts/login/ yang tidak ada)
LOGIN_URL = '/admin/login/'
