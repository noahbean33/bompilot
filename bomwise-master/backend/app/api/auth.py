import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db, settings
from app.core.security import get_current_user
from app.models.user import User

from app.schemas.auth import LoginRequest, Token, UserCreate, UserResponse
from app.services.auth import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    create_user,
    get_password_hash,
    get_user_by_email,
    verify_password,
    verify_token,
)

router = APIRouter()

_COOKIE_MAX_AGE = settings.refresh_token_expire_days * 24 * 60 * 60


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=settings.environment == "production",
        samesite="strict",
        max_age=_COOKIE_MAX_AGE,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(user: UserCreate, db: Session = Depends(get_db)):
    if get_user_by_email(db, email=user.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    db_user = create_user(db, user)

    # Generate password-reset token so user can set their password
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(UTC) + timedelta(hours=24)

    from app.models.password_reset_token import PasswordResetToken

    db.add(PasswordResetToken(
        user_id=db_user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    ))
    db.commit()

    # Send password-set email (best-effort — don't fail registration if SMTP is down)
    try:
        from app.worker.email import send_set_password_email
        send_set_password_email(db_user.email, raw_token)
    except Exception:
        pass

    return db_user


# ---------------------------------------------------------------------------
# Login / session management
# ---------------------------------------------------------------------------

@router.post("/login", response_model=Token)
def login(
    response: Response,
    body: LoginRequest,
    db: Session = Depends(get_db),
):
    user = authenticate_user(db, email=body.email, password=body.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled. Contact support.",
        )
    access_token = create_access_token(
        data={"sub": user.email},
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )
    refresh_token = create_refresh_token(data={"sub": user.email})
    _set_refresh_cookie(response, refresh_token)
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/refresh", response_model=Token)
def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing",
        )
    token_data = verify_token(refresh_token, token_type="refresh")
    if token_data is None or token_data.email is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
    user = get_user_by_email(db, email=token_data.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    new_access_token = create_access_token(
        data={"sub": user.email},
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )
    new_refresh_token = create_refresh_token(data={"sub": user.email})
    _set_refresh_cookie(response, new_refresh_token)
    user.last_login_at = datetime.now(UTC)
    db.commit()
    return {"access_token": new_access_token, "token_type": "bearer"}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("refresh_token")
    return {"detail": "Logged out"}


# ---------------------------------------------------------------------------
# Update user profile
# ---------------------------------------------------------------------------

class UpdateProfileRequest(BaseModel):
    name: str | None = None


@router.patch("/me", response_model=UserResponse)
def update_profile(
    body: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update user's name."""
    if body.name is not None:
        current_user.name = body.name
    db.commit()
    db.refresh(current_user)
    return current_user


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user


# ---------------------------------------------------------------------------
# Password management
# ---------------------------------------------------------------------------

class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """
    Generate a password reset token and email it. Always returns 200 to
    prevent user enumeration — even if the email is not registered.
    """
    from app.models.password_reset_token import PasswordResetToken
    from app.worker.email import send_password_reset_email

    user = get_user_by_email(db, email=body.email)
    if user and user.is_active:
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = datetime.now(UTC) + timedelta(hours=1)
        db.add(PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        ))
        db.commit()
        try:
            send_password_reset_email(user.email, raw_token)
        except Exception:
            pass  # Don't leak errors

    return {"detail": "If that email is registered, you'll receive a reset link."}


@router.post("/reset-password")
def reset_password(body: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Validate a reset token and update the user's password."""
    from app.models.password_reset_token import PasswordResetToken

    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    reset_token = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used == False,  # noqa: E712
        )
        .first()
    )
    if reset_token is None:
        raise HTTPException(status_code=400, detail="Invalid or already-used reset token")
    if reset_token.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
        raise HTTPException(status_code=400, detail="Reset token has expired")

    user = db.query(User).filter(User.id == reset_token.user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="User not found")

    user.hashed_password = get_password_hash(body.new_password)
    reset_token.used = True
    # If email was never verified, mark it as verified now (user proved inbox ownership by clicking link)
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
    db.commit()
    return {"detail": "Password updated successfully"}


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update password after verifying the current one (authenticated endpoint)."""
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_user.hashed_password = get_password_hash(body.new_password)
    db.commit()
    return {"detail": "Password changed successfully"}
