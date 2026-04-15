#!/bin/bash
set -e

echo "Starting Hedge Fund V7 LLM Worker (llm_slow queue)..."
echo "Waiting for dependencies..."
sleep 3

# Low concurrency on purpose: LLM calls are expensive and rate-limited.
exec celery -A app.celery_app worker \
    --loglevel=info \
    --concurrency=2 \
    -Q llm_slow \
    -n worker-llm@%h
