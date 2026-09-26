from datetime import UTC
from typing import Annotated, Literal
from fastapi import Form, HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, field_validator


class EvidenceProvenance(BaseModel):
    """Uploader declarations, separate from server-measured evidence identity."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    evidence_kind: Literal["real", "synthetic", "unknown"] = "unknown"
    source_organization: str = Field(default="", max_length=200)
    source_reference: str = Field(default="", max_length=500)
    dataset_version: str = Field(default="", max_length=200)
    acquired_at: AwareDatetime | None = None
    declared_crs: str = Field(default="", max_length=120)
    prior_processing: str = Field(default="", max_length=2000)
    added_by: str = Field(default="", max_length=200)

    @field_validator("acquired_at")
    @classmethod
    def normalize_acquisition_time(cls, value):
        return value.astimezone(UTC) if value is not None else None


def parse_provenance(provenance: Annotated[str, Form(max_length=12000)] = "{}") -> dict[str, object]:
    try:
        return EvidenceProvenance.model_validate_json(provenance).model_dump(mode="json")
    except ValidationError as error:
        raise HTTPException(status_code=422, detail="Invalid evidence provenance: use real, synthetic or unknown and a timestamp with timezone; check field lengths and supported fields.") from error
