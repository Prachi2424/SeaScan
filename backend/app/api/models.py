from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.core.config import Settings, get_settings
from app.ml.unet import build_unet

router = APIRouter(tags=["model"])
logger = logging.getLogger(__name__)
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
Score = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class TrainingMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trained_at: datetime
    epoch: PositiveInt
    dataset_sample_count: PositiveInt
    validation_dice: Score
    validation_iou: Score | None = None
    training_epochs: PositiveInt | None = None
    input_shape: tuple[PositiveInt, PositiveInt, PositiveInt] | None = None
    dataset_provenance: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def validate_relationships(self) -> TrainingMetadata:
        if self.training_epochs is not None and self.training_epochs < self.epoch:
            raise ValueError("training_epochs cannot precede the checkpoint epoch.")
        if self.input_shape is not None:
            channels, height, width = self.input_shape
            if channels != 3 or height % 16 or width % 16:
                raise ValueError("input_shape must be [3, height, width] with spatial dimensions divisible by 16.")
        return self


class Sidecar(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weights_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_metadata: dict[str, JsonValue]


class ModelMetrics(BaseModel):
    weights_sha256: str
    checkpoint_epoch: int
    training_epochs: int | None
    dice_score: float
    iou: float | None
    metric_source: str


class ModelInfo(BaseModel):
    architecture: str
    architecture_parameters: dict[str, int]
    weights_path: str
    weights_sha256: str
    metadata_path: str | None
    metadata_source: str
    input_shape: tuple[int, int, int] | None
    trained_at: datetime
    dataset_sample_count: int
    dataset_provenance: dict[str, JsonValue] | None
    metrics: ModelMetrics
    missing_fields: list[str]


def reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON constant: {value}")


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def file_signature(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def read_model(settings: Settings) -> ModelInfo:
    path = settings.resolved_model_weights_path
    if path is None:
        raise HTTPException(503, "Set SEASCAN_MODEL_WEIGHTS_PATH to a trained SeaScan checkpoint.")
    if not path.is_file():
        raise HTTPException(503, "The configured model checkpoint is unavailable.")
    try:
        import torch

        before = file_signature(path)
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
            stream.seek(0)
            checkpoint = torch.load(stream, map_location="cpu", weights_only=True)
        sha256 = digest.hexdigest()
        if not isinstance(checkpoint, dict) or "model_state_dict" not in checkpoint:
            raise ValueError("Checkpoint must include model_state_dict.")
        embedded = checkpoint.get("training_metadata")
        if not isinstance(embedded, dict):
            raise ValueError("Checkpoint has no training provenance.")
        TrainingMetadata.model_validate(embedded)
        combined = dict(embedded)
        metadata_path = path.with_name(f"{path.name}.metadata.json")
        metadata_source = "checkpoint"
        resolved_metadata_path: str | None = None
        if metadata_path.exists():
            with metadata_path.open("rb") as stream:
                raw = stream.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("Metadata JSON exceeds the 1 MiB limit.")
            sidecar = Sidecar.model_validate(json.loads(
                raw.decode("utf-8"), parse_constant=reject_constant,
                object_pairs_hook=unique_object,
            ))
            if sidecar.weights_sha256 != sha256:
                raise ValueError("Metadata checksum does not match the checkpoint.")
            for key, value in sidecar.training_metadata.items():
                if key in combined and combined[key] != value:
                    raise ValueError(f"Sidecar conflicts with checkpoint metadata field: {key}")
                combined[key] = value
            metadata_source = "checkpoint and checksum-bound metadata JSON"
            resolved_metadata_path = str(metadata_path)
        training = TrainingMetadata.model_validate(combined)
        model = build_unet()
        model.load_state_dict(checkpoint["model_state_dict"], strict=True)
        model.eval()
        for tensor in model.state_dict().values():
            if tensor.is_floating_point() and not torch.isfinite(tensor).all().item():
                raise ValueError("Checkpoint contains non-finite model parameters.")
        if file_signature(path) != before:
            raise ValueError("Checkpoint changed while reading; retry the request.")
        metrics = ModelMetrics(
            weights_sha256=sha256, checkpoint_epoch=training.epoch,
            training_epochs=training.training_epochs,
            dice_score=training.validation_dice, iou=training.validation_iou,
            metric_source=metadata_source,
        )
        return ModelInfo(
            architecture="SeaScan UNet",
            architecture_parameters={
                "input_channels": 3, "output_channels": 1, "base_channels": 32,
                "encoder_levels": 4,
                "parameter_count": sum(p.numel() for p in model.parameters()),
            },
            weights_path=str(path), weights_sha256=sha256,
            metadata_path=resolved_metadata_path, metadata_source=metadata_source,
            input_shape=training.input_shape, trained_at=training.trained_at,
            dataset_sample_count=training.dataset_sample_count,
            dataset_provenance=training.dataset_provenance, metrics=metrics,
            missing_fields=[name for name, value in {
                "training_epochs": training.training_epochs,
                "iou": training.validation_iou,
                "input_shape": training.input_shape,
                "dataset_provenance": training.dataset_provenance,
            }.items() if value is None],
        )
    except Exception as error:
        logger.exception("Unable to inspect configured SeaScan model")
        raise HTTPException(503, (
            "Model provenance is unavailable: the checkpoint or metadata is unreadable, "
            "invalid, incompatible, or inconsistent. Check the backend logs for details."
        )) from error


@router.get("/model/info", response_model=ModelInfo)
def model_info(response: Response, settings: Settings = Depends(get_settings)) -> ModelInfo:
    response.headers["Cache-Control"] = "no-store"
    return read_model(settings)


@router.get("/model/metrics", response_model=ModelMetrics)
def model_metrics(response: Response, settings: Settings = Depends(get_settings)) -> ModelMetrics:
    response.headers["Cache-Control"] = "no-store"
    return read_model(settings).metrics
