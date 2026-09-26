from __future__ import annotations

import sqlite3
from collections.abc import Generator

from app.core.config import get_settings


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS investigations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_assets (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL,
    asset_type TEXT NOT NULL CHECK(asset_type IN ('satellite', 'ais', 'environment')),
    original_filename TEXT NOT NULL,
    stored_filename TEXT NOT NULL,
    media_type TEXT,
    byte_size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(investigation_id) REFERENCES investigations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_assets_investigation ON evidence_assets(investigation_id);

CREATE TABLE IF NOT EXISTS analysis_results (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL,
    result_type TEXT NOT NULL CHECK(result_type IN ('satellite_detection', 'drift_backward', 'drift_forward', 'attribution')),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(investigation_id) REFERENCES investigations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS release_scenario_results (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL,
    result_type TEXT NOT NULL CHECK(result_type = 'release_scenarios'),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(investigation_id) REFERENCES investigations(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_release_scenarios_case ON release_scenario_results(investigation_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_analysis_investigation_type
ON analysis_results(investigation_id, result_type, created_at DESC);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('investigator', 'analyst', 'administrator')),
    password_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
    created_at TEXT NOT NULL,
    created_by TEXT
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry ON auth_sessions(expires_at);
"""


def initialize_database() -> None:
    settings = get_settings()
    database_path = settings.database_path
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.executescript(SCHEMA)
        if settings.environment.lower() == "development":
            _seed_demo_users(connection, settings.demo_user_password)
        elif connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            if not settings.bootstrap_admin_password:
                raise RuntimeError("Set SEASCAN_BOOTSTRAP_ADMIN_PASSWORD for the first production startup.")
            _seed_users(connection, (("admin", "SeaScan Administrator", "administrator"),), settings.bootstrap_admin_password)


def _seed_demo_users(connection: sqlite3.Connection, password: str) -> None:
    _seed_users(connection, (
        ("investigator", "Ira Investigator", "investigator"),
        ("analyst", "Arun Analyst", "analyst"),
        ("admin", "Aditi Administrator", "administrator"),
    ), password)


def _seed_users(connection: sqlite3.Connection, accounts: tuple[tuple[str, str, str], ...], password: str) -> None:
    import uuid
    from datetime import UTC, datetime
    from app.auth.security import hash_password
    now = datetime.now(UTC).isoformat()
    for username, display_name, role in accounts:
        if connection.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone() is None:
            connection.execute(
                "INSERT INTO users (id, username, display_name, role, password_hash, active, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
                (str(uuid.uuid4()), username, display_name, role, hash_password(password), now),
            )


def get_connection() -> Generator[sqlite3.Connection, None, None]:
    # FastAPI resolves synchronous dependencies in a worker thread before an async upload handler resumes.
    # One connection is still scoped to one request, so disabling SQLite's thread guard is safe here.
    connection = sqlite3.connect(get_settings().database_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
