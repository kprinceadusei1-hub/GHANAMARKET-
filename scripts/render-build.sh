#!/usr/bin/env bash
# Render build step: install, collect static files, apply migrations, create the first admin.
# Never seeds preview listings: production starts with real ads only.
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py ensure_superuser
python manage.py check --deploy --fail-level ERROR
