#!/usr/bin/env bash
# ==============================================================================
# DOTMIND 24/7 Cloud Production Startup Script
# Automatically launches @google/genai microservice & FastAPI core backend
# ==============================================================================
set -e

APP_PORT="${PORT:-8000}"

echo "=================================================================="
echo "  🧠 DOTMIND Mobile Personal AI Agent — Cloud Production Starting"
echo "  Target Port: ${APP_PORT}"
echo "=================================================================="

# 1. Start official @google/genai Node.js SDK service in the background
if [ -d "/app/genai-service" ] && [ -f "/app/genai-service/server.js" ]; then
    echo "  🚀 Starting @google/genai SDK Service on http://127.0.0.1:8001..."
    (cd /app/genai-service && node server.js) &
    GENAI_PID=$!
    trap "kill -9 $GENAI_PID 2>/dev/null || true" EXIT INT TERM
    export DOTMIND_USE_GENAI_SERVICE=true
    sleep 1.5
fi

# 2. Start FastAPI Core Backend via Uvicorn
echo "  🚀 Starting FastAPI Core Server on 0.0.0.0:${APP_PORT}..."
echo "  Health Check: http://0.0.0.0:${APP_PORT}/health"
echo "  API Docs:     http://0.0.0.0:${APP_PORT}/docs"
echo "=================================================================="

cd /app/backend
exec uvicorn app.main:app --host 0.0.0.0 --port "${APP_PORT}" --workers 1 --proxy-headers --forwarded-allow-ips='*'
