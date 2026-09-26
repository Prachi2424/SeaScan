from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.db.database import get_connection
from app.schemas.investigation import InvestigationCreate, InvestigationDetail, InvestigationSummary
from app.services.investigations import create_investigation, get_investigation, list_investigations, latest_analysis_results

router = APIRouter(prefix="/investigations", tags=["investigations"])
DatabaseConnection = Annotated[sqlite3.Connection, Depends(get_connection)]


@router.post("", response_model=InvestigationSummary, status_code=status.HTTP_201_CREATED)
def create(payload: InvestigationCreate, connection: DatabaseConnection) -> InvestigationSummary:
    return create_investigation(connection, payload)


@router.get("", response_model=list[InvestigationSummary])
def list_all(connection: DatabaseConnection) -> list[InvestigationSummary]:
    return list_investigations(connection)


@router.get("/{investigation_id}", response_model=InvestigationDetail)
def get_one(investigation_id: str, connection: DatabaseConnection) -> InvestigationDetail:
    detail = get_investigation(connection, investigation_id)
    detail.analyses = latest_analysis_results(connection, investigation_id)
    return detail
