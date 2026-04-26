"""Version endpoint — returns the current application version and commit hash."""

import os
import subprocess
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class VersionResponse(BaseModel):
    version: str
    commit: str
    environment: str


def _get_version() -> str:
    """Read version from VERSION file or APP_VERSION env var."""
    # First check env var (set by Docker build arg)
    env_version = os.environ.get("APP_VERSION")
    if env_version and env_version != "unknown":
        return env_version
    # Fallback: read VERSION file (works in local dev)
    version_file = Path(__file__).parent.parent.parent.parent / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return os.environ.get("APP_VERSION", "unknown")


def _get_commit() -> str:
    """Get short git commit hash."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return os.environ.get("GIT_COMMIT", "unknown")


@router.get("/version", response_model=VersionResponse)
async def get_version():
    """Return the current application version."""
    return VersionResponse(
        version=_get_version(),
        commit=_get_commit(),
        environment=os.environ.get("ENVIRONMENT", "development"),
    )


@router.get("/health")
async def health_check():
    """Health check endpoint — used by Docker health checks."""
    return {"status": "ok"}