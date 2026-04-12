#!/bin/bash
set -e

echo "Waiting for PostgreSQL..."
while ! python -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.connect(('db', 5432))
    s.close()
    exit(0)
except:
    exit(1)
" 2>/dev/null; do
    echo "PostgreSQL not ready, waiting 1s..."
    sleep 1
done
echo "PostgreSQL is ready!"

echo "Applying database migrations..."
python manage.py migrate --noinput

echo "Starting Gunicorn..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
