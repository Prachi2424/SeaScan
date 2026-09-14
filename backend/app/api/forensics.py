from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends

from app.ais.attribution import SCORE_WEIGHTS, rank_candidates
from app.core.config import Settings, get_settings
from app.db.database import get_connection
from app.drift.advection import load_environment_observations, simulate_particles
from app.schemas.forensics import AttributionRequest, AttributionResponse, DriftRequest, DriftResponse
from app.services.investigations import get_asset, record_analysis

router = APIRouter(tags=["forensics"])
DatabaseConnection = Annotated[sqlite3.Connection, Depends(get_connection)]
AppSettings = Annotated[Settings, Depends(get_settings)]


@router.post("/drift/forward", response_model=DriftResponse)
def forward_drift(payload: DriftRequest, connection: DatabaseConnection, settings: AppSettings) -> DriftResponse:
    return _run_drift(payload, connection, settings, direction=1)


@router.post("/drift/backward", response_model=DriftResponse)
def backward_drift(payload: DriftRequest, connection: DatabaseConnection, settings: AppSettings) -> DriftResponse:
    return _run_drift(payload, connection, settings, direction=-1)


def _run_drift(payload: DriftRequest, connection: sqlite3.Connection, settings: Settings, direction: int) -> DriftResponse:
    asset, stored_filename = get_asset(connection, payload.environmental_asset_id, "environment")
    file_path = settings.project_data_directories[0] / "environment" / stored_filename
    if not file_path.is_file():
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Environmental evidence file is no longer available on local storage.")
    observations = load_environment_observations(file_path, asset.metadata)
    result = simulate_particles(observations, latitude=payload.latitude, longitude=payload.longitude, observed_at=payload.observed_at, duration_hours=payload.duration_hours, step_minutes=payload.step_minutes, particle_count=payload.particle_count, initial_spread_meters=payload.initial_spread_meters, windage_factor=payload.windage_factor, direction=direction, random_seed=payload.random_seed)
    response = DriftResponse(direction="forward" if direction == 1 else "backward", seed={"latitude": payload.latitude, "longitude": payload.longitude, "observed_at": payload.observed_at.isoformat(), "duration_hours": payload.duration_hours, "particle_count": payload.particle_count}, **result)
    record_analysis(connection, asset.investigation_id, f"drift_{response.direction}", response.model_dump(mode="json"))
    return response


@router.post("/attribution/rank", response_model=AttributionResponse)
def rank_vessels(payload: AttributionRequest, connection: DatabaseConnection, settings: AppSettings) -> AttributionResponse:
    asset, stored_filename = get_asset(connection, payload.ais_asset_id, "ais")
    file_path = settings.project_data_directories[0] / "ais" / stored_filename
    if not file_path.is_file():
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="AIS evidence file is no longer available on local storage.")
    candidates = rank_candidates(file_path, asset.metadata, origin_latitude=payload.origin_latitude, origin_longitude=payload.origin_longitude, estimated_origin_at=payload.estimated_origin_at, search_radius_km=payload.search_radius_km, temporal_window_minutes=payload.temporal_window_minutes, behavior_window_hours=payload.behavior_window_hours)
    response = AttributionResponse(disclaimer="Candidate ranking is an explainable investigative lead based on uploaded evidence. It does not establish legal guilt or responsibility.", candidate_count=len(candidates), scoring_formula=SCORE_WEIGHTS, candidates=candidates)
    record_analysis(connection, asset.investigation_id, "attribution", response.model_dump(mode="json"))
    return response
