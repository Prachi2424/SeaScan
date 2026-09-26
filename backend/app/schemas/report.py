from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.forensics import AttributionResponse, DriftResponse


class ForensicReportRequest(BaseModel):
    """Select an investigation; report evidence is loaded only from server records."""

    model_config = ConfigDict(extra="forbid")

    investigation_id: str = Field(min_length=36, max_length=36)


class ReportAnalysisBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release_scenarios: dict[str, object] | None = None
    spill_geojson: dict[str, object] | None = None
    satellite_validation: dict[str, object] | None = None
    backward_drift: DriftResponse | None = None
    forward_drift: DriftResponse | None = None
    attribution: AttributionResponse | None = None


class ReportPackageManifest(BaseModel):
    schema_version: str
    report_filename: str
    report_sha256: str
    generated_at: str
    investigation_id: str
    evidence_assets: list[dict[str, object]]
    legal_notice: str
