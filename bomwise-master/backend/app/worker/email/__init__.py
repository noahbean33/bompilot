"""
Email digest sender.

send_digest_email(user_id) builds a plain-text digest of all unacknowledged
flags for the given user's parts (grouped by project) and sends it via SMTP.
"""

import logging
import smtplib
from email.mime.text import MIMEText

from sqlalchemy.orm import Session

from app.core.database import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Digest content builder (pure logic, no I/O — easy to unit test)
# ---------------------------------------------------------------------------


def build_digest(user_id: int, db: Session) -> tuple[str, str, str] | None:
    """
    Return (to_address, subject, body) or None if no unacknowledged flags.

    Imports are deferred so this module can be imported without a live DB.
    """
    from app.models.part_flag import PartFlag
    from app.models.part_result import PartResult as PartResultRow
    from app.models.project import BomLine, Project
    from app.models.user import User

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return None

    rows = (
        db.query(PartFlag, PartResultRow, BomLine, Project)
        .join(PartResultRow, PartResultRow.id == PartFlag.part_result_id)
        .join(BomLine, BomLine.id == PartResultRow.bom_line_id)
        .join(Project, Project.id == BomLine.project_id)
        .filter(Project.user_id == user_id, PartFlag.acknowledged == False)  # noqa: E712
        .order_by(Project.name, PartFlag.created_at)
        .all()
    )

    if not rows:
        return None

    # Group by project
    by_project: dict[str, list[str]] = {}
    for flag, part_result, bom_line, project in rows:
        key = project.name
        if key not in by_project:
            by_project[key] = []
        if flag.flag_type == "out_of_stock":
            line = (
                f"  [{bom_line.reference or '?'}] {part_result.mpn} — OUT OF STOCK "
                f"(was {flag.old_value})"
            )
        else:
            line = (
                f"  [{bom_line.reference or '?'}] {part_result.mpn} — PRICE CHANGE "
                f"{flag.old_value} → {flag.new_value}"
            )
        by_project[key].append(line)

    body_lines = ["BOMexplorer daily digest — unacknowledged alerts\n"]
    for project_name, flag_lines in by_project.items():
        body_lines.append(f"Project: {project_name}")
        body_lines.extend(flag_lines)
        body_lines.append("")

    body_lines.append("Log in to BOMexplorer to acknowledge these alerts.")
    body = "\n".join(body_lines)
    subject = f"BOMexplorer: {sum(len(v) for v in by_project.values())} alert(s) need your attention"
    return user.email, subject, body


# ---------------------------------------------------------------------------
# SMTP send helper (thin wrapper — easy to mock in tests)
# ---------------------------------------------------------------------------


def _send_smtp(to_address: str, subject: str, body: str) -> None:
    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = settings.email_from
    msg["To"] = to_address

    # Port 465 = implicit TLS (SMTP_SSL); port 587 = STARTTLS upgrade.
    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port) as smtp:
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
            if settings.smtp_user:
                smtp.starttls()
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)

    logger.info("Email sent to %s", to_address)


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Set-password email (new account — same mechanism as password reset)
# ---------------------------------------------------------------------------


def send_set_password_email(to_address: str, raw_token: str) -> None:
    """
    Send a set-your-password email for newly created accounts.
    The link goes to /reset-password so the user can set their initial password.
    """
    from app.core.database import settings as _settings

    base_url = getattr(_settings, "app_base_url", "http://localhost:5173")
    reset_link = f"{base_url}/reset-password?token={raw_token}"

    body = (
        "Welcome to BOMexplorer!\n\n"
        "Your account has been created. Please click the link below to set your password "
        "and start using BOMexplorer (valid for 24 hours):\n\n"
        f"  {reset_link}\n\n"
        "If you did not create an account, you can safely ignore this email.\n"
    )
    subject = "BOMexplorer — set your password"
    _send_smtp(to_address, subject, body)
    logger.info("Set-password email sent to %s", to_address)


# ---------------------------------------------------------------------------
# Password reset email
# ---------------------------------------------------------------------------


def send_password_reset_email(to_address: str, reset_token: str) -> None:
    """
    Send a password reset link to the given address.

    reset_token is the *raw* (unhashed) token — embed it in the link URL.
    The caller is responsible for storing the hashed form in the DB.
    """
    from app.core.database import settings as _settings

    # In a real deployment APP_BASE_URL would be set in .env.
    # Fall back to localhost for dev.
    base_url = getattr(_settings, "app_base_url", "http://localhost:5173")
    reset_link = f"{base_url}/reset-password?token={reset_token}"

    body = (
        "You (or an administrator) requested a password reset for your BOMexplorer account.\n\n"
        f"Click the link below to set a new password (valid for 24 hours):\n\n"
        f"  {reset_link}\n\n"
        "If you did not request this, you can safely ignore this email.\n"
    )
    subject = "BOMexplorer — password reset"
    _send_smtp(to_address, subject, body)
    logger.info("Password reset email sent to %s", to_address)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def send_digest_email(user_id: int, *, db: Session | None = None) -> bool:
    """
    Build and send a digest email for the given user.
    If db is provided it will be used (and NOT closed); otherwise a new session
    is created and closed after use.
    Returns True if an email was sent, False if there was nothing to report.
    """
    own_session = db is None
    if own_session:
        from app.core.database import SessionLocal
        db = SessionLocal()

    try:
        result = build_digest(user_id, db)
        if result is None:
            return False
        to_address, subject, body = result
        _send_smtp(to_address, subject, body)
        return True
    finally:
        if own_session:
            db.close()
