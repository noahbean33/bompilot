from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    name: str | None = None


class UserResponse(BaseModel):
    id: int
    email: str
    name: str | None = None
    subscription_tier: str
    is_active: bool
    is_admin: bool = False
    created_at: datetime
    email_verified_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    trial_ends_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    email: Optional[str] = None
