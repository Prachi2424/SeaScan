from __future__ import annotations

import sqlite3
from typing import Annotated

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, Response

from app.db.database import get_connection
from app.schemas.investigation import InvestigationCreate, InvestigationDetail, InvestigationSummary
from app.services.investigations import create_investigation, get_asset, get_investigation, get_report_file, list_investigations, latest_analysis_results
from app.core.config import Settings, get_settings
from app.auth.dependencies import require_roles
from app.schemas.auth import AuthUser

router = APIRouter(prefix="/investigations", tags=["investigations"])
DatabaseConnection = Annotated[sqlite3.Connection, Depends(get_connection)]


@router.post("", response_model=InvestigationSummary, status_code=status.HTTP_201_CREATED)
def create(payload: InvestigationCreate, connection: DatabaseConnection, _: Annotated[AuthUser, Depends(require_roles("investigator", "administrator"))]) -> InvestigationSummary:
    return create_investigation(connection, payload)


@router.get("", response_model=list[InvestigationSummary])
def list_all(connection: DatabaseConnection) -> list[InvestigationSummary]:
    return list_investigations(connection)


@router.get("/{investigation_id}", response_model=InvestigationDetail)
def get_one(investigation_id: str, connection: DatabaseConnection) -> InvestigationDetail:
    detail = get_investigation(connection, investigation_id)
    detail.analyses = latest_analysis_results(connection, investigation_id)
    return detail


@router.get("/{investigation_id}/assets/{asset_id}/preview")
def asset_preview(investigation_id: str, asset_id: str, connection: DatabaseConnection, settings: Annotated[Settings, Depends(get_settings)]) -> Response:
    asset, stored_filename = get_asset(connection, asset_id, "satellite")
    if asset.investigation_id != investigation_id:
        raise HTTPException(status_code=404, detail="Evidence asset not found in this investigation.")
    path = settings.project_data_directories[0] / "satellite" / stored_filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Stored satellite evidence is unavailable.")
    if path.suffix.lower() == ".png":
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})
    try:
        import io
        import numpy as np
        import rasterio
        from PIL import Image
        with rasterio.open(path) as dataset:
            band = dataset.read(1).astype("float32")
        finite = band[np.isfinite(band)]
        if finite.size == 0:
            raise ValueError("Raster contains no finite pixels")
        low, high = np.percentile(finite, [2, 98])
        scaled = np.clip((band - low) / max(float(high - low), 1e-6) * 255, 0, 255).astype("uint8")
        output = io.BytesIO()
        Image.fromarray(scaled, mode="L").save(output, format="PNG")
        return Response(output.getvalue(), media_type="image/png", headers={"Cache-Control": "private, max-age=300"})
    except Exception as error:
        raise HTTPException(status_code=422, detail="Unable to render a preview for this satellite raster.") from error


@router.get("/{investigation_id}/assets/{asset_id}/ground-truth-preview")
def ground_truth_preview(investigation_id: str, asset_id: str, connection: DatabaseConnection, settings: Annotated[Settings, Depends(get_settings)]) -> FileResponse:
    asset, _ = get_asset(connection, asset_id, "satellite")
    if asset.investigation_id != investigation_id:
        raise HTTPException(status_code=404, detail="Evidence asset not found in this investigation.")
    ground_truth = asset.metadata.get("ground_truth")
    if not isinstance(ground_truth, dict) or not isinstance(ground_truth.get("stored_filename"), str):
        raise HTTPException(status_code=404, detail="No ground-truth mask is stored for this satellite evidence.")
    path = settings.project_data_directories[0] / "satellite_ground_truth" / ground_truth["stored_filename"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Stored ground-truth mask is unavailable.")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


@router.get("/{investigation_id}/reports/{report_id}")
def saved_report(investigation_id: str, report_id: str, connection: DatabaseConnection, settings: Annotated[Settings, Depends(get_settings)]) -> FileResponse:
    filename, stored_filename, media_type = get_report_file(connection, investigation_id, report_id)
    path = settings.project_data_directories[1] / "reports" / stored_filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Saved report file is unavailable.")
    return FileResponse(path, media_type=media_type, filename=filename)
