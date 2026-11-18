"""Explicit production settings. Secrets are supplied by systemd, never bundled."""
import os

if not os.environ.get('DJANGO_SECRET_KEY'):
    raise RuntimeError('Production requires DJANGO_SECRET_KEY')

from .settings import *

LOCAL_ONLY = False
DEBUG = False
ALLOWED_HOSTS = ['tuysqan-coffee.com', 'www.tuysqan-coffee.com', '127.0.0.1', 'localhost']
CSRF_TRUSTED_ORIGINS = ['https://tuysqan-coffee.com', 'https://www.tuysqan-coffee.com']
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': os.environ['POSTGRES_DB'],
    'USER': os.environ['POSTGRES_USER'],
    'PASSWORD': os.environ['POSTGRES_PASSWORD'],
    'HOST': '127.0.0.1', 'PORT': '5432',
    'CONN_MAX_AGE': 60, 'CONN_HEALTH_CHECKS': True,
    'OPTIONS': {'connect_timeout': 5, 'options': '-c statement_timeout=15000 -c lock_timeout=10000'},
}}
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r'^internal/monitor-health/$', r'^internal/developer-bot-status/$']
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = 86400
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_REFERRER_POLICY = 'same-origin'
STATIC_ROOT = Path('/srv/tuysqan/shared/staticfiles')
MENU_UPLOAD_DIR = Path('/srv/tuysqan/shared/uploads/menu')
CACHES = {'default': {
    'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
    'LOCATION': '/srv/tuysqan/shared/cache',
    'OPTIONS': {'MAX_ENTRIES': 5000},
}}
MONITOR_CONFIG_PATH = Path('/etc/tuysqan/monitor.json')
MONITOR_STATE_DIR = Path('/srv/tuysqan/shared/monitor')
LOGGING = {
    'version': 1, 'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': 'WARNING'},
    'loggers': {'django': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False}},
}
