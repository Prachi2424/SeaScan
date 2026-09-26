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
        """Array adapter for PNGs and small in-memory callers."""
        _, height, width = image.shape
        return self.predict_windows(
            lambda y, x, h, w: image[:, y:y+h, x:x+w], height, width,
            image[:, ::max(1, (height + 511) // 512), ::max(1, (width + 511) // 512)],
        )

    def predict_windows(self, read_window, height, width, sample, tile_size=256, overlap=64):
        """Bound model activations to one tile; blend with shared scene normalization."""
        import numpy as np
        import torch
        import torch.nn.functional as functional

        if tile_size < 16 or tile_size % 16 or not 0 <= overlap < tile_size:
            raise ValueError("Tile size must be a multiple of 16; overlap must be smaller than the tile.")
        if height < 1 or width < 1 or height * width > 16_777_216:
            raise HTTPException(status_code=422, detail="Satellite image exceeds the 16,777,216-pixel processing limit. Crop the scene before uploading.")
        limits = []
        for band in sample:
            finite = band[np.isfinite(band)]
            if not finite.size:
                raise HTTPException(status_code=422, detail="No valid pixels in a sampled satellite band. Crop to valid coverage and retry.")
            lower, upper = np.percentile(finite, (2, 98))
            limits.append((lower, upper if upper > lower else lower + 1.0))
        model = self._load_model()
        accumulated = np.zeros((height, width), dtype=np.float32)
        weights = np.zeros_like(accumulated)
        for y in _tile_starts(height, tile_size, overlap):
            for x in _tile_starts(width, tile_size, overlap):
                h, w = min(tile_size, height-y), min(tile_size, width-x)
                pixels = read_window(y, x, h, w)
                valid = np.isfinite(pixels).all(axis=0)
                if not valid.any():
                    continue
                normalised = np.empty_like(pixels, dtype=np.float32)
                for band, (lower, upper) in enumerate(limits):
                    normalised[band] = np.clip((np.nan_to_num(pixels[band], nan=lower, posinf=upper, neginf=lower)-lower)/(upper-lower), 0, 1)
                tensor = torch.from_numpy(normalised).unsqueeze(0)
                pad_h, pad_w = (-h) % 16, (-w) % 16
                mode = "reflect" if pad_h < h and pad_w < w else "replicate"
                tensor = functional.pad(tensor, (0, pad_w, 0, pad_h), mode=mode)
                with torch.inference_mode():
                    probability = torch.sigmoid(model(tensor))[0, 0, :h, :w].cpu().numpy()
                # Positive weights retain image borders while de-emphasizing tile edges.
                blend = np.outer(np.maximum(np.hanning(h), .05), np.maximum(np.hanning(w), .05)).astype(np.float32)
                blend *= valid
                accumulated[y:y+h, x:x+w] += probability * blend
                weights[y:y+h, x:x+w] += blend
        np.divide(accumulated, weights, out=accumulated, where=weights > 0)
        accumulated[weights == 0] = 0
        return accumulated

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
            "probability_interpretation": "overlap-weighted mean of sigmoid outputs from the configured checkpoint; not a calibrated probability",
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


def _tile_starts(length, tile_size, overlap):
    if length <= tile_size:
        return [0]
    starts = list(range(0, length-tile_size+1, tile_size-overlap))
    if starts[-1] != length-tile_size:
        starts.append(length-tile_size)
    return starts
