from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends

from app.ais.attribution import SCORE_WEIGHTS, rank_candidates
from app.core.config import Settings, get_settings
from app.db.database import get_connection
from app.drift.advection import load_environment_observations, simulate_particles
from app.schemas.forensics import AttributionRequest, AttributionResponse, DriftRequest, DriftResponse, ReleaseScenarioRequest
from app.services.investigations import get_asset, record_analysis, latest_analysis_results

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
    response = DriftResponse(direction="forward" if direction == 1 else "backward", seed={"latitude": payload.latitude, "longitude": payload.longitude, "observed_at": payload.observed_at.isoformat(), "duration_hours": payload.duration_hours, "particle_count": payload.particle_count}, parameters=payload, **result)
    record_analysis(connection, asset.investigation_id, f"drift_{response.direction}", response.model_dump(mode="json"))
    return response


@router.post("/attribution/rank", response_model=AttributionResponse)
def rank_vessels(payload: AttributionRequest, connection: DatabaseConnection, settings: AppSettings) -> AttributionResponse:
    asset, stored_filename = get_asset(connection, payload.ais_asset_id, "ais")
    file_path = settings.project_data_directories[0] / "ais" / stored_filename
    if not file_path.is_file():
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="AIS evidence file is no longer available on local storage.")
    region = heading = None
    if payload.use_hindcast_region:
        import pandas as pd
        from pyproj import Geod
        from fastapi import HTTPException
        backward = latest_analysis_results(connection, asset.investigation_id).get("drift_backward")
        features = backward.get("trajectory", {}).get("features", []) if backward else []
        if not features:
            raise HTTPException(status_code=422, detail="Run a backward hindcast in this case before using its origin region.")
        final = features[-1]
        lon, lat = final["geometry"]["coordinates"]
        expected = pd.Timestamp(final["properties"]["timestamp"])
        supplied = pd.Timestamp(payload.estimated_origin_at)
        if supplied.tzinfo is None: supplied = supplied.tz_localize("UTC")
        geod = Geod(ellps="WGS84")
        if abs((expected-supplied).total_seconds())>60 or geod.inv(lon,lat,payload.origin_longitude,payload.origin_latitude)[2]>100:
            raise HTTPException(status_code=422, detail="Origin does not match the latest hindcast. Use hindcast origin again, or rank with manual coordinates.")
        region = backward.get("probability_region")
        if len(features)>1:
            previous = features[-2]["geometry"]["coordinates"]
            azimuth, _, distance = geod.inv(lon,lat,*previous)
            if distance>1: heading=azimuth
    excluded = []
    candidates = rank_candidates(file_path, asset.metadata, origin_latitude=payload.origin_latitude, origin_longitude=payload.origin_longitude, estimated_origin_at=payload.estimated_origin_at, search_radius_km=payload.search_radius_km, temporal_window_minutes=payload.temporal_window_minutes, behavior_window_hours=payload.behavior_window_hours, origin_region=region, release_heading=heading, exclusions=excluded)
    response = AttributionResponse(disclaimer="Candidate ranking is an explainable investigative lead based on uploaded evidence. It does not establish legal guilt or responsibility.", candidate_count=len(candidates), scoring_formula=SCORE_WEIGHTS, candidates=candidates, parameters=payload, excluded_vessels=excluded, ranking_version="2.0", ranking_context={"origin_region": region, "release_heading_degrees": heading, "interpolation_gap_limit_minutes": 60, "interpolation_speed_limit_knots": 60, "time_window_semantics": "plus/minus requested minutes around estimated release time"})
    record_analysis(connection, asset.investigation_id, "attribution", response.model_dump(mode="json"))
    return response


@router.post('/release-scenarios')
def release_scenarios(payload: ReleaseScenarioRequest, connection: DatabaseConnection, settings: AppSettings):
    from fastapi import HTTPException
    from pyproj import Geod
    environment, env_name = get_asset(connection, payload.drift.environmental_asset_id, 'environment')
    ais, ais_name = get_asset(connection, payload.ais_asset_id, 'ais')
    if environment.investigation_id != ais.investigation_id:
        raise HTTPException(status_code=422, detail='Environmental and AIS evidence must belong to the same case.')
    if payload.drift.particle_count > 200 or payload.drift.step_minutes < 30:
        raise HTTPException(status_code=422, detail='Scenario exploration allows at most 200 particles and steps of at least 30 minutes.')
    env_path = settings.project_data_directories[0] / 'environment' / env_name
    ais_path = settings.project_data_directories[0] / 'ais' / ais_name
    if not env_path.is_file() or not ais_path.is_file():
        raise HTTPException(status_code=410, detail='Required evidence file is missing from storage.')
    observations = load_environment_observations(env_path, environment.metadata)
    scenarios = []
    for duration in payload.durations_hours:
        try:
            args = payload.drift.model_dump(exclude={'environmental_asset_id', 'duration_hours'})
            result = simulate_particles(observations, **args, duration_hours=duration, direction=-1)
            features = result['trajectory']['features']
            final = features[-1]
            lon, lat = final['geometry']['coordinates']
            heading = None
            if len(features) > 1:
                azimuth, _, distance = Geod(ellps='WGS84').inv(lon, lat, *features[-2]['geometry']['coordinates'])
                if distance > 1: heading = azimuth
            excluded = []
            candidates = rank_candidates(ais_path, ais.metadata, origin_latitude=lat, origin_longitude=lon,
                estimated_origin_at=final['properties']['timestamp'], search_radius_km=payload.search_radius_km,
                temporal_window_minutes=payload.temporal_window_minutes, behavior_window_hours=24,
                origin_region=result['probability_region'], release_heading=heading, exclusions=excluded)
            scenarios.append(dict(duration_hours=duration, status='complete', origin=final,
                candidate_count=len(candidates), candidates=candidates, excluded_vessels=excluded,
                sampling=result['sampling'], probability_region=result['probability_region']))
        except HTTPException as error:
            if error.status_code != 422: raise
            scenarios.append(dict(duration_hours=duration, status='unavailable', error=str(error.detail)))
    response = dict(parameters=payload.model_dump(mode='json'), scenarios=scenarios, scoring_weights=SCORE_WEIGHTS,
        disclaimer='User-selected release-time scenarios, not a validated spill-age estimate or confidence interval. Vessel evidence scores are uncalibrated and cannot establish release time. No scenario is automatically selected. Environment warnings and AIS gaps affect comparison.')
    record_analysis(connection, environment.investigation_id, 'release_scenarios', response)
    return response
