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

CREATE INDEX IF NOT EXISTS idx_analysis_investigation_type
ON analysis_results(investigation_id, result_type, created_at DESC);
"""


def initialize_database() -> None:
    settings = get_settings()
    database_path = settings.database_path
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.executescript(SCHEMA)


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
