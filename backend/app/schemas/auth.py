from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Role = Literal["investigator", "analyst", "administrator"]


class AuthUser(BaseModel):
    id: str
    username: str
    display_name: str
    role: Role
    active: bool
    created_at: datetime


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=256)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: AuthUser


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")
    display_name: str = Field(min_length=2, max_length=120)
    role: Role
    password: str = Field(min_length=12, max_length=256)

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: str) -> str:
        if not (any(c.islower() for c in value) and any(c.isupper() for c in value) and any(c.isdigit() for c in value)):
            raise ValueError("Password must contain uppercase, lowercase, and numeric characters.")
        return value


class UserUpdate(BaseModel):
    role: Role | None = None
    active: bool | None = None
