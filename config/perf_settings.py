"""Explicitly opt-in local PostgreSQL benchmark. Never falls back to business DB."""
import json
import os
from pathlib import Path
from .settings import *

if os.environ.get('TUYSQAN_PERF_LOCAL') != '1':
    raise RuntimeError('Only an explicitly enabled local performance fixture may use these settings')
secrets_path = Path(os.environ['TUYSQAN_PERF_SECRETS']).resolve()
fixture = json.loads(secrets_path.read_text())
if not fixture['database'].startswith('tuysqan_perf_') or fixture['host'] != '127.0.0.1':
    raise RuntimeError('Refusing a database outside the dedicated local benchmark')
SECRET_KEY = fixture['secret_key']
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql', 'NAME': fixture['database'],
    'USER': fixture['user'], 'PASSWORD': fixture['password'],
    'HOST': '127.0.0.1', 'PORT': str(fixture['pg_port']),
    'CONN_MAX_AGE': 60, 'CONN_HEALTH_CHECKS': True,
    'OPTIONS': {'connect_timeout': 5, 'options': '-c statement_timeout=15000 -c lock_timeout=10000'},
}}
SESSION_COOKIE_NAME = 'tuysqan_perf_session'
CSRF_COOKIE_NAME = 'tuysqan_perf_csrf'
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
SMS_BACKEND = 'disabled'
PASSWORD_HASHERS = ['django.contrib.auth.hashers.PBKDF2PasswordHasher']
