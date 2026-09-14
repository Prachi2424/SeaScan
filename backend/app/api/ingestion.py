from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.ais.validation import validate_ais_file
from app.core.config import Settings, get_settings
from app.db.database import get_connection
from app.geospatial.environment import validate_environment_file
from app.geospatial.satellite import segment_satellite
from app.schemas.ingestion import IngestionResponse, SatelliteDetectionResponse
from app.services.investigations import record_analysis, record_asset
from app.services.storage import discard_upload, store_upload

router = APIRouter(tags=["real-data ingestion"])
DatabaseConnection = Annotated[sqlite3.Connection, Depends(get_connection)]
AppSettings = Annotated[Settings, Depends(get_settings)]


@router.post("/ais/upload", response_model=IngestionResponse, status_code=status.HTTP_201_CREATED)
async def upload_ais(
    investigation_id: Annotated[str, Form(min_length=36, max_length=36)],
    file: Annotated[UploadFile, File(description="Real AIS CSV or Parquet export.")],
    connection: DatabaseConnection,
    settings: AppSettings,
) -> IngestionResponse:
    stored = await store_upload(file, settings, "ais")
    try:
        validation = validate_ais_file(stored.path)
        asset = record_asset(connection, investigation_id=investigation_id, asset_type="ais", original_filename=stored.original_filename, stored_filename=stored.stored_filename, media_type=file.content_type, byte_size=stored.byte_size, sha256=stored.sha256, metadata=validation)
    except Exception:
        discard_upload(stored)
        raise
    return IngestionResponse(asset=asset, validation=validation)


@router.post("/environment/upload", response_model=IngestionResponse, status_code=status.HTTP_201_CREATED)
async def upload_environment(
    investigation_id: Annotated[str, Form(min_length=36, max_length=36)],
    file: Annotated[UploadFile, File(description="Real CSV, GeoJSON, or NetCDF environmental observations.")],
    connection: DatabaseConnection,
    settings: AppSettings,
) -> IngestionResponse:
    stored = await store_upload(file, settings, "environment")
    try:
        validation = validate_environment_file(stored.path)
        asset = record_asset(connection, investigation_id=investigation_id, asset_type="environment", original_filename=stored.original_filename, stored_filename=stored.stored_filename, media_type=file.content_type, byte_size=stored.byte_size, sha256=stored.sha256, metadata=validation)
    except Exception:
        discard_upload(stored)
        raise
    return IngestionResponse(asset=asset, validation=validation)


@router.post("/satellite/upload", response_model=SatelliteDetectionResponse, status_code=status.HTTP_201_CREATED)
async def upload_satellite(
    investigation_id: Annotated[str, Form(min_length=36, max_length=36)],
    file: Annotated[UploadFile, File(description="Real GeoTIFF or PNG satellite image.")],
    connection: DatabaseConnection,
    settings: AppSettings,
    threshold: Annotated[float, Form(ge=0.001, le=0.999)] = 0.5,
    west: Annotated[float | None, Form()] = None,
    south: Annotated[float | None, Form()] = None,
    east: Annotated[float | None, Form()] = None,
    north: Annotated[float | None, Form()] = None,
) -> SatelliteDetectionResponse:
    bounds_values = (west, south, east, north)
    if any(value is not None for value in bounds_values) and any(value is None for value in bounds_values):
        from fastapi import HTTPException
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Provide all of west, south, east, and north to georeference a PNG.")
    stored = await store_upload(file, settings, "satellite")
    try:
        geojson, model, validation = segment_satellite(stored.path, settings=settings, threshold=threshold, bounds=bounds_values if all(value is not None for value in bounds_values) else None)
        asset = record_asset(connection, investigation_id=investigation_id, asset_type="satellite", original_filename=stored.original_filename, stored_filename=stored.stored_filename, media_type=file.content_type, byte_size=stored.byte_size, sha256=stored.sha256, metadata={**validation, "model": model})
    except Exception:
        discard_upload(stored)
        raise
    response = SatelliteDetectionResponse(asset=asset, validation=validation, geojson=geojson, model=model)
    record_analysis(connection, investigation_id, "satellite_detection", response.model_dump(mode="json"))
    return response
