#!/usr/bin/env bash
###############################################################################
# deploy.sh — Production deploy script for Hetzner VPS
#
# Usage (on the VPS):
#   cd /opt/bomwise && ./scripts/deploy.sh
#
# What it does:
#   1. Pulls latest code from GitHub
#   2. Creates a git tag from VERSION file
#   3. Builds Docker images
#   4. Starts containers with docker-compose.prod.yml
#   5. Runs database migrations
#   6. Cleans up old images
###############################################################################

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY_REPO="https://github.com/futureshocked/bomwise.git"
BRANCH="master"

log()  { echo -e "${GREEN}[DEPLOY]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; }

###############################################################################
# 0. Pre-flight checks
###############################################################################
log "Checking prerequisites..."

command -v docker >/dev/null 2>&1 || { err "docker not found — install it first"; exit 1; }
command -v docker compose >/dev/null 2>&1 || { err "docker compose plugin not found — install it first"; exit 1; }
command -v git >/dev/null 2>&1 || { err "git not found — install it first"; exit 1; }

if [ ! -f "$APP_DIR/.env" ]; then
    err ".env file not found in $APP_DIR"
    warn "Copy your production .env file first:"
    warn "  cp .env.production.example \"$APP_DIR/.env\""
    warn "  # Then edit and fill real values"
    exit 1
fi

###############################################################################
# 1. Get or clone repository
###############################################################################
if [ ! -d "$APP_DIR/.git" ]; then
    log "Cloning repository into $APP_DIR..."
    # If the repo wasn't there, we need to fetch it
    # Move current files (like .env) aside, clone, then move back
    mkdir -p "$APP_DIR/.tmp_deploy"
    cp "$APP_DIR/.env" "$APP_DIR/.tmp_deploy/.env" 2>/dev/null || true
    # We actually expect you to have cloned already, so skip
    warn "No .git found — deploy expects the repo to be cloned on the VPS first."
    warn "Run: git clone $DEPLOY_REPO $APP_DIR"
    exit 1
fi

cd "$APP_DIR"

###############################################################################
# 2. Pull latest code
###############################################################################
log "Pulling latest from $BRANCH..."
git stash --include-untracked 2>/dev/null || true
git pull origin "$BRANCH" || { err "git pull failed"; exit 1; }

###############################################################################
# 3. Version tag
###############################################################################
VERSION=$(cat VERSION | tr -d '[:space:]')
TAG="v${VERSION}"

# Write APP_VERSION and GIT_COMMIT into .env for runtime access
# Also export for docker-compose build args
export APP_VERSION="$VERSION"
export GIT_COMMIT=$(git rev-parse --short HEAD || echo "unknown")

# Ensure .env has the latest version values
if grep -q '^APP_VERSION=' "$APP_DIR/.env" 2>/dev/null; then
    sed -i "s/^APP_VERSION=.*/APP_VERSION=$VERSION/" "$APP_DIR/.env"
    sed -i "s/^GIT_COMMIT=.*/GIT_COMMIT=$GIT_COMMIT/" "$APP_DIR/.env"
else
    echo "APP_VERSION=$VERSION" >> "$APP_DIR/.env"
    echo "GIT_COMMIT=$GIT_COMMIT" >> "$APP_DIR/.env"
fi

if git tag -l "$TAG" | grep -q "$TAG"; then
    warn "Tag $TAG already exists, skipping tag creation."
else
    log "Creating git tag $TAG..."
    git tag "$TAG" 2>/dev/null || true
    git push origin "$TAG" 2>/dev/null || warn "Could not push tag (may be OK on deploy-only server)"
fi

log "Deploying version $VERSION..."

###############################################################################
# 4. Build + start containers
###############################################################################
log "Building Docker images..."
docker compose -f docker-compose.prod.yml build --no-cache=false

log "Starting containers..."
docker compose -f docker-compose.prod.yml up -d

###############################################################################
# 5. Database migrations
###############################################################################
log "Running Alembic migrations..."
sleep 5  # Give backend time to start
docker compose -f docker-compose.prod.yml exec -T backend \
    uv run alembic upgrade head || {
        warn "Migration failed — check logs:"
        warn "  docker compose -f docker-compose.prod.yml logs backend"
    }

###############################################################################
# 6. Cleanup
###############################################################################
log "Cleaning up old Docker images..."
docker system prune -f --filter "until=24h"

###############################################################################
# 7. Health check
###############################################################################
log "Checking application health..."
sleep 3
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/docs 2>/dev/null || echo "000")

if [ "$HTTP_CODE" = "200" ]; then
    log "✓ Backend is running (HTTP $HTTP_CODE)"
else
    warn "Backend health check returned HTTP $HTTP_CODE"
    warn "Check logs: docker compose -f docker-compose.prod.yml logs backend"
fi

log ""
log "═══════════════════════════════════════════"
log "  Deploy complete — bomwise $VERSION"
log "  Tag: $TAG"
log "═══════════════════════════════════════════"