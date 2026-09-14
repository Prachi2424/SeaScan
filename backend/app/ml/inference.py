from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import HTTPException, status

from app.core.config import Settings


class SegmentationRunner:
    """Loads a trained state dictionary and returns its direct sigmoid probabilities."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._weights_path = settings.resolved_model_weights_path

    def assert_ready(self) -> None:
        if self._weights_path is None or not self._weights_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Satellite inference requires SEASCAN_MODEL_WEIGHTS_PATH pointing to a trained compatible U-Net checkpoint. SeaScan will not fabricate segmentation confidence without trained weights.",
            )

    def _load_model(self):
        import torch

        from app.ml.unet import build_unet

        self.assert_ready()
        assert self._weights_path is not None
        try:
            checkpoint = torch.load(self._weights_path, map_location="cpu", weights_only=True)
            if not isinstance(checkpoint, dict) or "model_state_dict" not in checkpoint or "training_metadata" not in checkpoint:
                raise ValueError("Expected a SeaScan training checkpoint with provenance metadata.")
            state_dict = checkpoint["model_state_dict"]
            _validate_training_metadata(checkpoint["training_metadata"])
            model = build_unet()
            model.load_state_dict(state_dict, strict=True)
            model.eval()
            return model
        except Exception as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="The configured U-Net checkpoint is unreadable or incompatible with SeaScan's model architecture.") from error

    def predict(self, image):
        import numpy as np
        import torch
        import torch.nn.functional as functional

        model = self._load_model()
        normalised = _normalise_per_band(image)
        _, height, width = normalised.shape
        pad_height = (16 - height % 16) % 16
        pad_width = (16 - width % 16) % 16
        tensor = torch.from_numpy(normalised).unsqueeze(0)
        tensor = functional.pad(tensor, (0, pad_width, 0, pad_height), mode="reflect")
        with torch.inference_mode():
            output = torch.sigmoid(model(tensor)).squeeze(0).squeeze(0).cpu().numpy()
        return output[:height, :width].astype(np.float32)

    def model_metadata(self) -> dict[str, object]:
        import torch

        self.assert_ready()
        assert self._weights_path is not None
        checkpoint = torch.load(self._weights_path, map_location="cpu", weights_only=True)
        if not isinstance(checkpoint, dict) or "training_metadata" not in checkpoint:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Configured weights do not include required SeaScan training provenance.")
        training_metadata = _validate_training_metadata(checkpoint["training_metadata"])
        return {
            "architecture": "SeaScan UNet (3-band, base_channels=32)",
            "weights_sha256": _sha256(self._weights_path),
            "probability_interpretation": "sigmoid output of the configured trained checkpoint",
            "training": training_metadata,
        }


def _normalise_per_band(image):
    import numpy as np

    output = np.zeros_like(image, dtype=np.float32)
    for index, band in enumerate(image):
        finite_values = band[np.isfinite(band)]
        if finite_values.size == 0:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Satellite raster contains no finite pixel values.")
        lower, upper = np.percentile(finite_values, (2, 98))
        if upper <= lower:
            upper = lower + 1.0
        output[index] = np.clip((np.nan_to_num(band, nan=lower) - lower) / (upper - lower), 0.0, 1.0)
    return output


def _sha256(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as weights_file:
        while chunk := weights_file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_training_metadata(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Configured checkpoint has invalid training provenance.")
    required = {"trained_at", "epoch", "dataset_sample_count", "validation_dice"}
    missing = required.difference(value)
    if missing:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Configured checkpoint lacks required training provenance fields.")
    return {key: value[key] for key in required}
