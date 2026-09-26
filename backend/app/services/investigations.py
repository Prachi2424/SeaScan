from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status

from app.schemas.investigation import EvidenceAsset, InvestigationCreate, InvestigationDetail, InvestigationSummary


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _asset_from_row(row: sqlite3.Row) -> EvidenceAsset:
    return EvidenceAsset(
        id=row["id"],
        investigation_id=row["investigation_id"],
        asset_type=row["asset_type"],
        original_filename=row["original_filename"],
        media_type=row["media_type"],
        byte_size=row["byte_size"],
        sha256=row["sha256"],
        metadata=json.loads(row["metadata_json"]),
        created_at=row["created_at"],
    )


def create_investigation(connection: sqlite3.Connection, payload: InvestigationCreate) -> InvestigationSummary:
    investigation_id = str(uuid.uuid4())
    now = _now()
    connection.execute(
        "INSERT INTO investigations (id, title, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (investigation_id, payload.title.strip(), payload.description.strip(), now, now),
    )
    return InvestigationSummary(
        id=investigation_id,
        title=payload.title.strip(),
        description=payload.description.strip(),
        created_at=now,
        updated_at=now,
    )


def list_investigations(connection: sqlite3.Connection) -> list[InvestigationSummary]:
    rows = connection.execute(
        "SELECT id, title, description, created_at, updated_at FROM investigations ORDER BY updated_at DESC"
    ).fetchall()
    return [InvestigationSummary(**dict(row)) for row in rows]


def get_investigation(connection: sqlite3.Connection, investigation_id: str) -> InvestigationDetail:
    row = connection.execute(
        "SELECT id, title, description, created_at, updated_at FROM investigations WHERE id = ?", (investigation_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investigation not found.")
    assets = connection.execute(
        "SELECT * FROM evidence_assets WHERE investigation_id = ? ORDER BY created_at DESC", (investigation_id,)
    ).fetchall()
    return InvestigationDetail(**dict(row), assets=[_asset_from_row(asset) for asset in assets])


def record_asset(
    connection: sqlite3.Connection,
    *,
    investigation_id: str,
    asset_type: str,
    original_filename: str,
    stored_filename: str,
    media_type: str | None,
    byte_size: int,
    sha256: str,
    metadata: dict[str, object],
) -> EvidenceAsset:
    get_investigation(connection, investigation_id)
    asset_id = str(uuid.uuid4())
    created_at = _now()
    connection.execute(
        """INSERT INTO evidence_assets
           (id, investigation_id, asset_type, original_filename, stored_filename, media_type, byte_size, sha256, metadata_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (asset_id, investigation_id, asset_type, original_filename, stored_filename, media_type, byte_size, sha256, json.dumps(metadata), created_at),
    )
    connection.execute("UPDATE investigations SET updated_at = ? WHERE id = ?", (created_at, investigation_id))
    return EvidenceAsset(
        id=asset_id,
        investigation_id=investigation_id,
        asset_type=asset_type,
        original_filename=original_filename,
        media_type=media_type,
        byte_size=byte_size,
        sha256=sha256,
        metadata=metadata,
        created_at=created_at,
    )


def get_asset(connection: sqlite3.Connection, asset_id: str, expected_type: str) -> tuple[EvidenceAsset, str]:
    row = connection.execute("SELECT * FROM evidence_assets WHERE id = ?", (asset_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence asset not found.")
    if row["asset_type"] != expected_type:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Evidence asset is {row['asset_type']}, not {expected_type}.")
    return _asset_from_row(row), row["stored_filename"]


def record_analysis(connection: sqlite3.Connection, investigation_id: str, result_type: str, payload: dict[str, object]) -> None:
    get_investigation(connection, investigation_id)
    table = "release_scenario_results" if result_type == "release_scenarios" else "analysis_results"
    connection.execute(
        f"INSERT INTO {table} (id, investigation_id, result_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), investigation_id, result_type, json.dumps(payload), _now()),
    )
    connection.execute("UPDATE investigations SET updated_at = ? WHERE id = ?", (_now(), investigation_id))


def latest_analysis_results(connection: sqlite3.Connection, investigation_id: str) -> dict[str, dict[str, object]]:
    get_investigation(connection, investigation_id)
    rows = connection.execute(
        """SELECT result_type, payload_json FROM analysis_results
           WHERE investigation_id = ? ORDER BY created_at DESC""",
        (investigation_id,),
    ).fetchall()
    rows += connection.execute("SELECT result_type, payload_json FROM release_scenario_results WHERE investigation_id = ? ORDER BY created_at DESC", (investigation_id,)).fetchall()
    results: dict[str, dict[str, object]] = {}
    for row in rows:
        if row["result_type"] not in results:
            results[row["result_type"]] = json.loads(row["payload_json"])
    return results
