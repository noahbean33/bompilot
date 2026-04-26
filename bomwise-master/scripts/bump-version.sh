#!/usr/bin/env bash
###############################################################################
# bump-version.sh — Bump the VERSION file and create a git commit + tag
#
# Usage:
#   ./scripts/bump-version.sh patch    # 1.0.0 → 1.0.1
#   ./scripts/bump-version.sh minor    # 1.0.0 → 1.1.0
#   ./scripts/bump-version.sh major    # 1.0.0 → 2.0.0
#   ./scripts/bump-version.sh set 2.5.0  # set to specific version
###############################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION_FILE="$(dirname "$SCRIPT_DIR")/VERSION"

if [ ! -f "$VERSION_FILE" ]; then
    echo "ERROR: VERSION file not found at $VERSION_FILE"
    exit 1
fi

CURRENT=$(cat "$VERSION_FILE" | tr -d '[:space:]')
MAJOR=$(echo "$CURRENT" | cut -d. -f1)
MINOR=$(echo "$CURRENT" | cut -d. -f2)
PATCH=$(echo "$CURRENT" | cut -d. -f3)

case "${1:-}" in
    patch)
        PATCH=$((PATCH + 1))
        NEW="$MAJOR.$MINOR.$PATCH"
        ;;
    minor)
        MINOR=$((MINOR + 1))
        PATCH=0
        NEW="$MAJOR.$MINOR.$PATCH"
        ;;
    major)
        MAJOR=$((MAJOR + 1))
        MINOR=0
        PATCH=0
        NEW="$MAJOR.$MINOR.$PATCH"
        ;;
    set)
        if [ -z "${2:-}" ]; then
            echo "Usage: $0 set X.Y.Z"
            exit 1
        fi
        NEW="$2"
        ;;
    *)
        echo "Usage: $0 {patch|minor|major|set X.Y.Z}"
        echo ""
        echo "Current version: $CURRENT"
        exit 1
        ;;
esac

echo "$NEW" > "$VERSION_FILE"
echo "Version bumped: $CURRENT → $NEW"

# Commit + tag if inside a git repo
if command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
    cd "$(dirname "$SCRIPT_DIR")"
    git add VERSION
    git commit -m "Bump version to $NEW"
    git tag "v$NEW"
    echo ""
    echo "Commited and tagged v$NEW"
    echo "Push with: git push origin master --tags"
fi