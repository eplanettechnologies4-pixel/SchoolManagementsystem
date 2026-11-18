import os
import sys
import shutil
import tempfile
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(os.path.join(BASE_DIR, '.env'))

# Robust serverless / Vercel runtime detection
def check_is_serverless():
    if any(k in os.environ for k in ('VERCEL', 'VERCEL_ENV', 'NOW_REGION', 'AWS_LAMBDA_FUNCTION_NAME', 'LAMBDA_TASK_ROOT')):
        return True
    base_posix = BASE_DIR.as_posix()
    if base_posix.startswith('/var/task') or base_posix.startswith('/var/runtime'):
        return True
    return False

IS_VERCEL = check_is_serverless()
IS_SERVERLESS = IS_VERCEL

# Include apps directory in Python path
sys.path.insert(0, os.path.join(BASE_DIR, 'apps'))

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-default-sms-2026-key')
DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 't')
ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', '*').split(',') if h.strip()]

# CSRF Trusted Origins for Vercel and local development
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.getenv(
        'CSRF_TRUSTED_ORIGINS',
        'https://*.vercel.app,http://127.0.0.1,http://localhost'
    ).split(',') if o.strip()
]

# Reverse Proxy & SSL Headers for Vercel / Cloud
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Custom User Model
AUTH_USER_MODEL = 'accounts.User'

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party apps
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'axes',

    # Local apps
    'accounts.apps.AccountsConfig',
    'academics.apps.AcademicsConfig',
    'students.apps.StudentsConfig',
    'fees.apps.FeesConfig',
    'staff.apps.StaffConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'axes.middleware.AxesMiddleware',
    'sms_core.middleware.RoleRoutingMiddleware',
]

ROOT_URLCONF = 'sms_core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'accounts.context_processors.user_role_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'sms_core.wsgi.application'

# Database Configuration (PostgreSQL / DATABASE_URL / SQLite with Vercel /tmp fallback)
DATABASE_URL = os.getenv('DATABASE_URL', '').strip()

if DATABASE_URL:
    import dj_database_url
    DATABASES = {
        'default': dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=600,
            conn_health_checks=True,
        )
    }
elif os.getenv('DATABASE_ENGINE') == 'django.db.backends.postgresql' and os.getenv('DATABASE_NAME'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('DATABASE_NAME', 'sms_db'),
            'USER': os.getenv('DATABASE_USER', 'postgres'),
            'PASSWORD': os.getenv('DATABASE_PASSWORD', ''),
            'HOST': os.getenv('DATABASE_HOST', 'localhost'),
            'PORT': os.getenv('DATABASE_PORT', '5432'),
        }
    }
else:
    # In Vercel / AWS Lambda serverless environments, /var/task is read-only.
    # We copy db.sqlite3 to the OS temp directory (e.g. /tmp/db.sqlite3 on Linux/Vercel)
    # and grant write permissions so database write operations succeed without OperationalError.
    is_readonly_env = IS_SERVERLESS or not os.access(str(BASE_DIR), os.W_OK)
    if is_readonly_env:
        tmp_dir = Path(tempfile.gettempdir())
        tmp_db = tmp_dir / 'db.sqlite3'
        src_db = BASE_DIR / 'db.sqlite3'
        if src_db.exists():
            if not tmp_db.exists() or tmp_db.stat().st_size == 0:
                try:
                    shutil.copyfile(src_db, tmp_db)
                    try:
                        os.chmod(tmp_db, 0o666)
                    except Exception:
                        pass
                except Exception as e:
                    print(f"Warning: Failed to copy db.sqlite3 to {tmp_db}: {e}")
        db_path = tmp_db
        # Use signed cookie session engine in serverless SQLite so sessions persist across ephemeral Lambda instances
        SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'
    else:
        db_path = BASE_DIR / 'db.sqlite3'

    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': db_path,
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

if DEBUG:
    PASSWORD_HASHERS = [
        'django.contrib.auth.hashers.MD5PasswordHasher',
    ]


# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static & Media files
STATIC_URL = '/static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Authentication URLs
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard_router'
LOGOUT_REDIRECT_URL = 'login'

# Django REST Framework Settings
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/day',
        'user': '1000/day',
    },
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}

# SimpleJWT Settings (10 min access token, rotation & blacklist)
from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=10),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# Authentication Backends (with django-axes)
AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# Django-Axes Brute Force Protection
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(hours=1)
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = 'auth/login.html'

# Session Security & Timeout
SESSION_COOKIE_AGE = 1800  # 30 minutes session timeout
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# School Branding
SCHOOL_NAME = 'E-Planet Educational Portal'

