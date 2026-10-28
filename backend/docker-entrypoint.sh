#!/bin/sh
set -e
# Apply schema migrations explicitly; the app never auto-creates tables.
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*"
