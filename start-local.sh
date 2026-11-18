#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  /opt/homebrew/bin/python3.11 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py setup_local
.venv/bin/python manage.py import_drinks
.venv/bin/python scripts/build_drinks_landing.py
exec .venv/bin/python manage.py runserver 127.0.0.1:8000 --noreload
