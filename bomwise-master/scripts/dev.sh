#!/bin/bash
set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Starting BOMexplorer dev environment..."

# Docker
echo "[1/4] Starting Docker services..."
docker compose -f "$PROJECT_ROOT/docker-compose.yml" up -d
echo "      Postgres + Redis up."

# Backend
echo "[2/4] Starting backend..."
cd "$PROJECT_ROOT/backend"
uv run uvicorn app.main:app --reload > /tmp/bomexplorer-backend.log 2>&1 &
BACKEND_PID=$!
echo "      PID $BACKEND_PID — logs: /tmp/bomexplorer-backend.log"

# Celery
echo "[3/4] Starting Celery worker..."
uv run celery -A app.worker worker --loglevel=info > /tmp/bomexplorer-celery.log 2>&1 &
CELERY_PID=$!
echo "      PID $CELERY_PID — logs: /tmp/bomexplorer-celery.log"

# Frontend
echo "[4/4] Starting frontend..."
cd "$PROJECT_ROOT/frontend"
npm run dev > /tmp/bomexplorer-frontend.log 2>&1 &
FRONTEND_PID=$!
echo "      PID $FRONTEND_PID — logs: /tmp/bomexplorer-frontend.log"

echo ""
echo "All services started."
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:5173"
echo ""
echo "To stop everything: kill $BACKEND_PID $CELERY_PID $FRONTEND_PID && docker compose -f $PROJECT_ROOT/docker-compose.yml stop"
echo "Or just close this terminal and run: pkill -f 'uvicorn|celery|vite'"