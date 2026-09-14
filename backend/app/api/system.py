from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from app.api.models import router as models_router
from app.core.config import Settings, get_settings
from app.schemas.system import HealthResponse, SystemConfigResponse

router = APIRouter(tags=["system"])
router.include_router(models_router)


@router.get("/health", response_model=HealthResponse, summary="Check API health")
def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="seascan-api",
        version="0.1.0",
        timestamp=datetime.now(UTC),
    )


@router.get("/system/config", response_model=SystemConfigResponse, summary="Read pipeline capabilities")
def system_config(settings: Settings = Depends(get_settings)) -> SystemConfigResponse:
    """Expose supported real-data inputs without revealing filesystem locations or secrets."""
    return SystemConfigResponse(
        environment=settings.environment,
        max_upload_size_mb=settings.max_upload_size_mb,
        accepted_satellite_formats=[".tif", ".tiff", ".png"],
        accepted_ais_formats=[".csv", ".parquet"],
        accepted_environmental_formats=[".csv", ".geojson", ".json", ".nc", ".nc4"],
        pipeline_stages=[
            "satellite_ingestion",
            "spill_segmentation",
            "environmental_fusion",
            "drift_hindcast",
            "ais_reconstruction",
            "explainable_vessel_ranking",
        ],
        satellite_inference_ready=bool(
            settings.resolved_model_weights_path and settings.resolved_model_weights_path.is_file()
        ),
    )
