from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class DriftRequest(BaseModel):
    environmental_asset_id: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    observed_at: datetime
    duration_hours: float = Field(gt=0, le=168)
    step_minutes: int = Field(default=30, ge=5, le=120)
    particle_count: int = Field(default=200, ge=20, le=1000)
    initial_spread_meters: float = Field(default=250, ge=0, le=10_000)
    windage_factor: float = Field(default=0.03, ge=0, le=0.1)
    random_seed: int = 42


class DriftResponse(BaseModel):
    direction: str
    seed: dict[str, object]
    trajectory: dict[str, object]
    probability_region: dict[str, object]
    sampling: dict[str, object]
    parameters: DriftRequest | None = None


class AttributionRequest(BaseModel):
    use_hindcast_region: bool = False
    ais_asset_id: str
    origin_latitude: float = Field(ge=-90, le=90)
    origin_longitude: float = Field(ge=-180, le=180)
    estimated_origin_at: datetime
    search_radius_km: float = Field(default=25, gt=0, le=500)
    temporal_window_minutes: int = Field(default=90, ge=5, le=1440)
    behavior_window_hours: int = Field(default=24, ge=1, le=168)


class CandidateVessel(BaseModel):
    mmsi: str
    vessel_type: str | None
    evidence_score: float
    score_breakdown: dict[str, float]
    evidence: dict[str, object]
    track_geojson: dict[str, object]


class AttributionResponse(BaseModel):
    disclaimer: str
    candidate_count: int
    scoring_formula: dict[str, float]
    excluded_vessels: list[dict[str, object]] = Field(default_factory=list)
    ranking_version: str = "legacy"
    ranking_context: dict[str, object] = Field(default_factory=dict)
    candidates: list[CandidateVessel]
    parameters: AttributionRequest | None = None


class ReleaseScenarioRequest(BaseModel):
    drift: DriftRequest
    ais_asset_id: str
    durations_hours: list[float] = Field(min_length=1, max_length=5)
    search_radius_km: float = Field(default=25, gt=0, le=500)
    temporal_window_minutes: int = Field(default=90, ge=5, le=1440)

    @field_validator('durations_hours')
    @classmethod
    def validate_durations(cls, values):
        import math
        if any(not math.isfinite(value) or not 1 <= value <= 72 for value in values):
            raise ValueError('Choose durations between 1 and 72 hours.')
        if len(set(values)) != len(values):
            raise ValueError('Durations must be unique.')
        return sorted(values)
