#!/usr/bin/env python
"""
Grant admin privileges to a user by email.

Usage:
    uv run python scripts/make_admin.py user@example.com

Works both locally (from project root) and inside the Docker backend container
(WORKDIR=/app, scripts mounted at /app/scripts).
"""

import sys
import os
from pathlib import Path

# Ensure the backend 'app' package is importable.
# Inside Docker: WORKDIR=/app, app package at /app/app/
# Local dev: project root, app package at backend/app/
_script_dir = Path(__file__).resolve().parent
if (_script_dir.parent / "app" / "__init__.py").exists():
    # Running from project root: scripts/make_admin.py
    backend_path = str(_script_dir.parent)
elif (_script_dir / "app" / "__init__.py").exists():
    # Running inside Docker: /app/scripts/make_admin.py, app at /app/app/
    backend_path = str(_script_dir.parent)
else:
    # Fallback: try ../backend from project root
    backend_path = str(_script_dir.parent / "backend")

if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# Load .env if DATABASE_URL is not already set (e.g. outside Docker).
if not os.environ.get("DATABASE_URL"):
    from dotenv import load_dotenv
    env_path = _script_dir.parent / "backend" / ".env"
    if env_path.exists():
        load_dotenv(env_path)


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: uv run python scripts/make_admin.py <email>")
        sys.exit(1)

    email = sys.argv[1].strip()

    from app.core.database import SessionLocal
    from app.models.user import User

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            print(f"User not found: {email}")
            sys.exit(1)
        if user.is_admin:
            print(f"{email} is already an admin.")
        else:
            user.is_admin = True
            db.commit()
            print(f"✓ {email} is now an admin.")
    finally:
        db.close()


if __name__ == "__main__":
    main()