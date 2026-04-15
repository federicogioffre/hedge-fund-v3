#!/bin/bash
set -e

echo "Starting Hedge Fund V3 Celery Worker..."
echo "Waiting for dependencies..."
sleep 3

exec celery -A app.celery_app worker --loglevel=info --concurrency=4 -Q celery,default
