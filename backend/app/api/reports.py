from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile

from app.db.database import get_connection
from app.schemas.forensics import AttributionResponse, DriftResponse
from app.schemas.report import ForensicReportRequest, ReportAnalysisBundle
from app.services.investigations import get_investigation, latest_analysis_results
from app.services.reports import build_report_package, package_zip
from app.core.config import get_settings
from app.services.signing import load_private_key, public_key_id, verify_package

router = APIRouter(prefix="/reports", tags=["reports"])
DatabaseConnection = Annotated[sqlite3.Connection, Depends(get_connection)]


def _report_data(connection: sqlite3.Connection, investigation_id: str) -> ReportAnalysisBundle:
    stored = latest_analysis_results(connection, investigation_id)
    satellite = stored.get("satellite_detection")
    return ReportAnalysisBundle(
        release_scenarios=stored.get("release_scenarios"),
        spill_geojson=satellite.get("geojson") if satellite else None,
        satellite_validation=satellite.get("validation") if satellite else None,
        backward_drift=DriftResponse.model_validate(stored["drift_backward"]) if "drift_backward" in stored else None,
        forward_drift=DriftResponse.model_validate(stored["drift_forward"]) if "drift_forward" in stored else None,
        attribution=AttributionResponse.model_validate(stored["attribution"]) if "attribution" in stored else None,
    )


@router.post("/forensic.pdf", response_class=Response)
def forensic_pdf(payload: ForensicReportRequest, connection: DatabaseConnection) -> Response:
    investigation = get_investigation(connection, payload.investigation_id)
    filename, report, manifest = build_report_package(investigation, _report_data(connection, investigation.id))
    return Response(
        content=report,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Report-SHA256": manifest.report_sha256,
            "Cache-Control": "no-store",
        },
    )


@router.post("/package.zip", response_class=Response)
def forensic_package(payload: ForensicReportRequest, connection: DatabaseConnection) -> Response:
    investigation = get_investigation(connection, payload.investigation_id)
    filename, report, manifest = build_report_package(investigation, _report_data(connection, investigation.id))
    try:
        package = package_zip(filename, report, manifest)
    except (OSError, RuntimeError, ValueError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    package_name = filename.removesuffix(".pdf") + "-package.zip"
    return Response(
        content=package,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{package_name}"', "Cache-Control": "no-store"},
    )


@router.post("/verify-package")
async def verify_evidence_package(file: UploadFile = File(...)) -> dict[str, object]:
    package = await file.read(100 * 1024 * 1024 + 1)
    if len(package) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Evidence package exceeds the 100 MB verification limit.")
    settings = get_settings()
    key_path = settings.resolved_signing_private_key_path
    trusted_ids: set[str] = set()
    if key_path and key_path.is_file():
        trusted_ids.add(public_key_id(load_private_key(key_path).public_key()))
    result = verify_package(package, trusted_ids)
    return result
