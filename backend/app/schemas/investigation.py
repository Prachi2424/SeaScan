from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class InvestigationCreate(BaseModel):
    title: str = Field(min_length=3, max_length=160, examples=["Arabian Sea slick — 2026-09-13"])
    description: str = Field(default="", max_length=2_000)


class InvestigationSummary(BaseModel):
    id: str
    title: str
    description: str
    created_at: datetime
    updated_at: datetime


class EvidenceAsset(BaseModel):
    id: str
    investigation_id: str
    asset_type: str
    original_filename: str
    media_type: str | None
    byte_size: int
    sha256: str
    metadata: dict[str, object]
    created_at: datetime


class InvestigationDetail(InvestigationSummary):
    assets: list[EvidenceAsset]
    analyses: dict[str, dict[str, object]] = Field(default_factory=dict)
