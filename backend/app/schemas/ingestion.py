from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.investigation import EvidenceAsset


class IngestionResponse(BaseModel):
    asset: EvidenceAsset
    validation: dict[str, object] = Field(description="Facts extracted from the uploaded real data.")


class SatelliteDetectionResponse(IngestionResponse):
    geojson: dict[str, object]
    model: dict[str, object]
