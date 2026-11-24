from datetime import timedelta
from pathlib import Path

from decouple import config

from gmp.config import Configurations

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = Configurations.secret_key
DEBUG = Configurations.debug
ALLOWED_HOSTS = Configurations.allowed_hosts

INSTALLED_APPS = [
    'unfold',  # must come before django.contrib.admin
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'rest_framework_simplejwt.token_blacklist',
    'drf_spectacular',
    'gmp_apps.common',
    'gmp_apps.authentication',
    'gmp_apps.membership',
    'gmp_apps.contact_admin',
    'gmp_apps.schemes',
    'gmp_apps.portals',
    'gmp_apps.content',
    'gmp_apps.notifications',
    'gmp_apps.dashboard',
    'gmp_apps.app_text',
    'gmp_apps.chatbot',
    'gmp_apps.member_documents',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# CORS: an explicit allow-list from the environment, never "allow all". The API authenticates with a
# Bearer token in a header (no cookies), so credentials are not allowed cross-origin. The admin site
# is same-origin only and is excluded.
CORS_ALLOWED_ORIGINS = Configurations.cors_allowed_origins
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = False
CORS_URLS_REGEX = r'^/(?!admin/).*$'

ROOT_URLCONF = 'gmp.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
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

WSGI_APPLICATION = 'gmp.wsgi.application'

if Configurations.db_engine == 'sqlite':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': Configurations.db_name,
            'USER': Configurations.db_user,
            'PASSWORD': Configurations.db_password,
            'HOST': Configurations.db_host,
            'PORT': Configurations.db_port,
        }
    }

AUTH_USER_MODEL = 'authentication.User'
AUTHENTICATION_BACKENDS = ['gmp_apps.authentication.backends.AdminSiteBackend']

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = Path(config('STATIC_ROOT', default=str(BASE_DIR / 'staticfiles')))  # collectstatic target; nginx serves it
MEDIA_ROOT = Path(config('MEDIA_ROOT', default=str(BASE_DIR / 'media')))
MEDIA_URL = '/media/'
# Members' identity documents live OUTSIDE MEDIA_ROOT: MEDIA_URL is public, these files are not.
PRIVATE_MEDIA_ROOT = Path(Configurations.private_media_root or str(BASE_DIR / 'private_media'))
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['gmp_apps.authentication.jwt.VersionedJWTAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_THROTTLE_RATES': {'auth': Configurations.auth_throttle_rate, 'chatbot': Configurations.chatbot_rate,
                               'member_document_upload': Configurations.member_document_upload_rate,
                               'app_text': Configurations.app_text_rate,
                               'contact_submit': Configurations.contact_public_submit_rate,
                               'contact_category': Configurations.contact_public_category_rate},
    'EXCEPTION_HANDLER': 'gmp_apps.common.exception_handler.api_exception_handler',
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=Configurations.access_token_minutes),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=Configurations.refresh_token_days),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'USER_ID_FIELD': 'user_id',
    'USER_ID_CLAIM': 'user_id',
    'AUTH_HEADER_TYPES': ('Bearer',),
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'Government Membership Platform API',
    'DESCRIPTION': 'Centralized backend for the website, mobile app and admin panel.',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}


CELERY_BROKER_URL = Configurations.celery_broker_url
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_IGNORE_RESULT = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BEAT_SCHEDULE = {
    'purge-chat-logs': {
        'task': 'gmp_apps.chatbot.tasks.purge_chat_logs',
        'schedule': 24 * 3600,
    },
    'sync-schemes': {
        'task': 'gmp_apps.schemes.tasks.sync_schemes',
        'schedule': Configurations.scheme_sync_interval_hours * 3600,
    },
    'expire-referral-invites': {
        'task': 'gmp_apps.membership.tasks.expire_referral_invites',
        'schedule': Configurations.invite_expiry_interval_minutes * 60,
    },
}

UNFOLD = {
    'DASHBOARD_CALLBACK': 'gmp_apps.common.dashboard.dashboard_callback',
    'SITE_TITLE': 'Government Membership Admin',
    'SITE_HEADER': 'Government Membership',
}

OTP_DELIVERY_BACKEND = Configurations.otp_delivery_backend

if not DEBUG:
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # nginx terminates TLS and sets X-Forwarded-Proto; without this the admin login fails the CSRF origin check.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

CSRF_TRUSTED_ORIGINS = Configurations.csrf_trusted_origins
