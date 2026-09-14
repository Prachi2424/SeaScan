from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.ingestion import router as ingestion_router
from app.api.investigations import router as investigations_router
from app.api.forensics import router as forensics_router
from app.api.system import router as system_router
from app.core.config import get_settings
from app.db.database import initialize_database

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Prepare local data directories before serving API traffic."""
    for directory in settings.project_data_directories:
        directory.mkdir(parents=True, exist_ok=True)
    initialize_database()
    yield


app = FastAPI(
    title="SeaScan API",
    description="Real-data oil-spill detection and maritime forensics service.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(origin).rstrip("/") for origin in settings.cors_origins],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

app.include_router(system_router, prefix=settings.api_v1_prefix)
app.include_router(investigations_router, prefix=settings.api_v1_prefix)
app.include_router(ingestion_router, prefix=settings.api_v1_prefix)
app.include_router(forensics_router, prefix=settings.api_v1_prefix)


@app.get("/", tags=["system"], include_in_schema=False)
def root() -> dict[str, str]:
    return {"service": "SeaScan API", "docs": "/docs"}
