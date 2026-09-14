from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.db.database import get_connection
from app.schemas.forensics import AttributionResponse, DriftResponse
from app.schemas.report import ForensicReportRequest, ReportAnalysisBundle
from app.services.investigations import get_investigation, latest_analysis_results
from app.services.reports import build_report_package, package_zip

router = APIRouter(prefix="/reports", tags=["reports"])
DatabaseConnection = Annotated[sqlite3.Connection, Depends(get_connection)]


def _report_data(connection: sqlite3.Connection, investigation_id: str) -> ReportAnalysisBundle:
    stored = latest_analysis_results(connection, investigation_id)
    satellite = stored.get("satellite_detection")
    return ReportAnalysisBundle(
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
    package = package_zip(filename, report, manifest)
    package_name = filename.removesuffix(".pdf") + "-package.zip"
    return Response(
        content=package,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{package_name}"', "Cache-Control": "no-store"},
    )
