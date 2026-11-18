"""Local-only prototype. Never use this configuration as production settings."""
from pathlib import Path
import os
import secrets
BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_FILE = BASE_DIR / '.local-secret'
if not os.environ.get('DJANGO_SECRET_KEY') and not SECRET_FILE.exists():
    SECRET_FILE.write_text(secrets.token_urlsafe(64))
    SECRET_FILE.chmod(0o600)
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY') or SECRET_FILE.read_text().strip()
DEBUG = False
ALLOWED_HOSTS = ['127.0.0.1', 'localhost', '[::1]', 'testserver']
INSTALLED_APPS = ['django.contrib.admin','django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles','core']
MIDDLEWARE = ['core.monitoring.RequestMetricsMiddleware','django.middleware.security.SecurityMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','django.contrib.messages.middleware.MessageMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[BASE_DIR/'templates'],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages','core.context_processors.common']}}]
WSGI_APPLICATION='config.wsgi.application'
# Acquire the SQLite write reservation before reading inside atomic operations.
# This prevents simultaneous writers from failing while upgrading deferred transactions.
DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':BASE_DIR/'db.sqlite3','OPTIONS':{'timeout':20,'transaction_mode':'IMMEDIATE'}}}
AUTH_PASSWORD_VALIDATORS=[{'NAME':'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},{'NAME':'django.contrib.auth.password_validation.MinimumLengthValidator'}]
LANGUAGE_CODE='ru'
TIME_ZONE='Asia/Aqtobe'
USE_I18N=True
USE_TZ=True
STATIC_URL='/static/'
STATICFILES_DIRS=[BASE_DIR/'static']
STATIC_ROOT=BASE_DIR/'staticfiles'
DEFAULT_AUTO_FIELD='django.db.models.BigAutoField'
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SAMESITE='Lax'
SESSION_EXPIRE_AT_BROWSER_CLOSE=True
CSRF_COOKIE_SAMESITE='Lax'
X_FRAME_OPTIONS='DENY'
SECURE_CONTENT_TYPE_NOSNIFF=True
DATA_UPLOAD_MAX_MEMORY_SIZE=1024*1024
LOGIN_URL='/staff/login/'
LOCAL_ONLY=True

SMS_BACKEND=os.environ.get('SMS_BACKEND','disabled')
SMS_TEST_TRANSPORT_ALLOWED=False

# Private monitoring paths can be supplied by the future Linux service environment.
MONITOR_CONFIG_PATH=Path(os.environ.get('TUYSQAN_MONITOR_CONFIG',str(BASE_DIR/'.local-monitoring.json')))
MONITOR_STATE_DIR=Path(os.environ.get('TUYSQAN_MONITOR_STATE',str(BASE_DIR/'.local-monitoring')))
