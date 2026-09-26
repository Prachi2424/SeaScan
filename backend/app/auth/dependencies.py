from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Annotated, Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.security import token_digest
from app.db.database import get_connection
from app.schemas.auth import AuthUser, Role

bearer = HTTPBearer(auto_error=False)
DatabaseConnection = Annotated[sqlite3.Connection, Depends(get_connection)]


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    connection: DatabaseConnection,
) -> AuthUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.", headers={"WWW-Authenticate": "Bearer"})
    now = datetime.now(UTC).isoformat()
    row = connection.execute(
        """SELECT u.* FROM auth_sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1""",
        (token_digest(credentials.credentials), now),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is invalid or expired.", headers={"WWW-Authenticate": "Bearer"})
    connection.execute("UPDATE auth_sessions SET last_seen_at = ? WHERE token_hash = ?", (now, token_digest(credentials.credentials)))
    return AuthUser(id=row["id"], username=row["username"], display_name=row["display_name"], role=row["role"], active=bool(row["active"]), created_at=row["created_at"])


def require_roles(*roles: Role) -> Callable[..., AuthUser]:
    def dependency(user: Annotated[AuthUser, Depends(get_current_user)]) -> AuthUser:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"This action requires one of these roles: {', '.join(roles)}.")
        return user
    return dependency
