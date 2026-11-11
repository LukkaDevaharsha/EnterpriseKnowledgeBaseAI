#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"
flask --app run:app db upgrade
exec gunicorn run:app --bind "0.0.0.0:${PORT:-10000}"
