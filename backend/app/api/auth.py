from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import bearer, get_current_user, require_roles
from app.auth.security import hash_password, new_session_token, token_digest, verify_password
from app.core.config import Settings, get_settings
from app.db.database import get_connection
from app.schemas.auth import AuthUser, LoginRequest, LoginResponse, UserCreate, UserUpdate

router = APIRouter(prefix="/auth", tags=["authentication"])
DatabaseConnection = Annotated[sqlite3.Connection, Depends(get_connection)]


def _user(row: sqlite3.Row) -> AuthUser:
    return AuthUser(id=row["id"], username=row["username"], display_name=row["display_name"], role=row["role"], active=bool(row["active"]), created_at=row["created_at"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, connection: DatabaseConnection, settings: Annotated[Settings, Depends(get_settings)]) -> LoginResponse:
    row = connection.execute("SELECT * FROM users WHERE lower(username) = lower(?)", (payload.username.strip(),)).fetchone()
    if row is None or not row["active"] or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password.")
    now = datetime.now(UTC)
    expires = now + timedelta(hours=settings.auth_session_hours)
    token, digest = new_session_token()
    connection.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (now.isoformat(),))
    connection.execute(
        "INSERT INTO auth_sessions (id, token_hash, user_id, created_at, expires_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), digest, row["id"], now.isoformat(), expires.isoformat(), now.isoformat()),
    )
    return LoginResponse(access_token=token, expires_at=expires, user=_user(row))


@router.get("/me", response_model=AuthUser)
def me(user: Annotated[AuthUser, Depends(get_current_user)]) -> AuthUser:
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(user: Annotated[AuthUser, Depends(get_current_user)], connection: DatabaseConnection, credentials=Depends(bearer)) -> None:
    del user
    if credentials:
        connection.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (token_digest(credentials.credentials),))


@router.get("/users", response_model=list[AuthUser])
def list_users(connection: DatabaseConnection, _: Annotated[AuthUser, Depends(require_roles("administrator"))]) -> list[AuthUser]:
    return [_user(row) for row in connection.execute("SELECT * FROM users ORDER BY active DESC, display_name COLLATE NOCASE").fetchall()]


@router.post("/users", response_model=AuthUser, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, connection: DatabaseConnection, administrator: Annotated[AuthUser, Depends(require_roles("administrator"))]) -> AuthUser:
    now = datetime.now(UTC).isoformat()
    user_id = str(uuid.uuid4())
    try:
        connection.execute(
            "INSERT INTO users (id, username, display_name, role, password_hash, active, created_at, created_by) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
            (user_id, payload.username.lower(), payload.display_name.strip(), payload.role, hash_password(payload.password), now, administrator.id),
        )
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That username already exists.") from error
    return _user(connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


@router.patch("/users/{user_id}", response_model=AuthUser)
def update_user(user_id: str, payload: UserUpdate, connection: DatabaseConnection, administrator: Annotated[AuthUser, Depends(require_roles("administrator"))]) -> AuthUser:
    row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if user_id == administrator.id and payload.active is False:
        raise HTTPException(status_code=422, detail="You cannot disable your own account.")
    if user_id == administrator.id and payload.role is not None and payload.role != "administrator":
        raise HTTPException(status_code=422, detail="You cannot remove your own administrator role.")
    removes_administrator = row["role"] == "administrator" and (payload.active is False or (payload.role is not None and payload.role != "administrator"))
    if removes_administrator:
        active_admins = connection.execute("SELECT COUNT(*) FROM users WHERE role = 'administrator' AND active = 1").fetchone()[0]
        if active_admins <= 1:
            raise HTTPException(status_code=422, detail="SeaScan must retain at least one active administrator.")
    role = payload.role or row["role"]
    active = int(payload.active if payload.active is not None else bool(row["active"]))
    connection.execute("UPDATE users SET role = ?, active = ? WHERE id = ?", (role, active, user_id))
    if not active:
        connection.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
    return _user(connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
