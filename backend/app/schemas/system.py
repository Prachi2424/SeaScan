from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(description="Service status.")
    service: str
    version: str
    timestamp: datetime


class SystemConfigResponse(BaseModel):
    environment: str
    max_upload_size_mb: int
    accepted_satellite_formats: list[str]
    accepted_ais_formats: list[str]
    accepted_environmental_formats: list[str]
    pipeline_stages: list[str]
    satellite_inference_ready: bool
