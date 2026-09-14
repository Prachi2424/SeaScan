from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from app.core.config import Settings

SATELLITE_SUFFIXES = {".tif", ".tiff", ".png"}


def segment_satellite(
    file_path: Path,
    *,
    settings: Settings,
    threshold: float,
    bounds: tuple[float, float, float, float] | None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    """Run an actual trained checkpoint over a raster and polygonize only model-positive pixels."""
    if file_path.suffix.lower() not in SATELLITE_SUFFIXES:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Satellite evidence must be GeoTIFF or PNG.")
    if not 0 < threshold < 1:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="threshold must be between 0 and 1.")

    from app.ml.inference import SegmentationRunner

    runner = SegmentationRunner(settings)
    runner.assert_ready()
    raster, transform, crs, source_metadata = _read_raster(file_path, bounds)
    probabilities = runner.predict(raster)
    return _polygonize(probabilities, threshold, transform, crs, source_metadata, runner.model_metadata())


def _read_raster(file_path: Path, bounds: tuple[float, float, float, float] | None):
    import numpy as np
    from PIL import Image
    from rasterio import Affine

    suffix = file_path.suffix.lower()
    if suffix == ".png":
        with Image.open(file_path) as image:
            image.load()
            array = np.asarray(image.convert("RGB"), dtype=np.float32).transpose(2, 0, 1)
        height, width = array.shape[1:]
        if bounds:
            west, south, east, north = bounds
            if not west < east or not south < north:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="PNG bounds must have west < east and south < north.")
            return array, Affine.from_gdal((east - west) / width, 0, west, 0, -(north - south) / height, north), "EPSG:4326", {"source_format": "png", "coordinate_reference": "EPSG:4326", "width": width, "height": height, "band_count": 3}
        return array, Affine.identity(), None, {"source_format": "png", "coordinate_reference": "image_pixels", "width": width, "height": height, "band_count": 3}

    try:
        import rasterio
        with rasterio.open(file_path) as dataset:
            if dataset.count == 0:
                raise ValueError("Raster has no bands.")
            indices = list(range(1, min(dataset.count, 3) + 1))
            array = dataset.read(indices, masked=True).filled(np.nan).astype(np.float32)
            while array.shape[0] < 3:
                array = np.concatenate([array, array[-1:, :, :]], axis=0)
            spatial_reference = str(dataset.crs) if dataset.crs else "image_pixels"
            return array, dataset.transform, dataset.crs, {"source_format": "geotiff", "coordinate_reference": spatial_reference, "width": dataset.width, "height": dataset.height, "band_count": dataset.count}
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The GeoTIFF cannot be read as a valid raster.") from error


def _polygonize(probabilities, threshold: float, transform, crs, source_metadata: dict[str, object], model_metadata: dict[str, object]):
    import numpy as np
    from rasterio.features import geometry_mask, shapes
    from rasterio.warp import transform_geom

    binary_mask = probabilities >= threshold
    feature_collection: dict[str, object] = {"type": "FeatureCollection", "features": []}
    features: list[dict[str, object]] = []
    for geometry, value in shapes(binary_mask.astype(np.uint8), mask=binary_mask, transform=transform):
        if not value:
            continue
        local_mask = geometry_mask([geometry], out_shape=binary_mask.shape, transform=transform, invert=True)
        component_probability = probabilities[local_mask]
        if component_probability.size == 0:
            continue
        output_geometry: dict[str, Any] = geometry
        if crs:
            output_geometry = transform_geom(crs, "EPSG:4326", geometry, precision=7)
        features.append(
            {
                "type": "Feature",
                "geometry": output_geometry,
                "properties": {
                    "mean_model_probability": round(float(component_probability.mean()), 6),
                    "max_model_probability": round(float(component_probability.max()), 6),
                    "pixel_count": int(component_probability.size),
                    "threshold": threshold,
                },
            }
        )
    feature_collection["features"] = features
    validation = {
        **source_metadata,
        "threshold": threshold,
        "positive_pixel_count": int(binary_mask.sum()),
        "component_count": len(features),
    }
    return feature_collection, model_metadata, validation
