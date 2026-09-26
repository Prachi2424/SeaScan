from __future__ import annotations

import math
import hashlib
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from app.core.config import Settings

SATELLITE_SUFFIXES = {".tif", ".tiff", ".png"}

# Plain PNG files do not carry a geographic transform.  Known demonstration
# evidence is therefore identified by its content hash, rather than trusting a
# filename that can be changed or accidentally reused for another image.
KNOWN_PNG_EVIDENCE: dict[str, dict[str, object]] = {
    "126d656b28c23b0e98c9e4531b08fd8919e1ed9119ec435eb26d270f9fa7615d": {
        "bounds": (-88.8509434, 29.0606100, -88.4597525, 29.2801243),
        "coordinate_reference": "EPSG:4326",
        "acquired_at": "2018-12-19T12:00:00Z",
        "source_organization": "Zenodo",
        "source_reference": "https://doi.org/10.5281/zenodo.4672426",
        "dataset": "Oil Spill Segmentation — Sentinel-1A GRD VV",
        "evidence_type": "real_observation_declared",
    }
}


def _sha256(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_bounds(bounds: tuple[float, float, float, float]) -> bool:
    west, south, east, north = bounds
    return all(math.isfinite(value) for value in bounds) and -180 <= west < east <= 180 and -90 <= south < north <= 90


def segment_satellite(
    file_path: Path,
    *,
    settings: Settings,
    threshold: float,
    bounds: tuple[float, float, float, float] | None,
    min_component_pixels: int = 0,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    """Run an actual trained checkpoint over a raster and polygonize only model-positive pixels."""
    if file_path.suffix.lower() not in SATELLITE_SUFFIXES:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Satellite evidence must be GeoTIFF or PNG.")
    if not 0 < threshold < 1:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="threshold must be between 0 and 1.")

    if not 0 <= min_component_pixels <= 1_000_000:
        raise HTTPException(status_code=422, detail="Minimum component size must be between 0 and 1,000,000 pixels.")

    from app.ml.inference import SegmentationRunner

    runner = SegmentationRunner(settings)
    runner.assert_ready()
    if file_path.suffix.lower() == ".png":
        from PIL import Image
        with Image.open(file_path) as image:
            _check_dimensions(image.width, image.height, png=True)
        raster, transform, crs, source_metadata = _read_raster(file_path, bounds)
        probabilities = runner.predict(raster)
    else:
        import numpy as np
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.windows import Window
        from rasterio.warp import transform_bounds
        try:
            with rasterio.open(file_path) as dataset:
                _check_dimensions(dataset.width, dataset.height)
                if dataset.count < 1:
                    raise HTTPException(status_code=422, detail="GeoTIFF contains no raster bands.")
                if not dataset.crs:
                    raise HTTPException(status_code=422, detail="GeoTIFF must include a coordinate reference system for map placement.")
                indices = list(range(1, min(dataset.count, 3) + 1))
                def bands(values):
                    values = values.astype(np.float32).filled(np.nan)
                    while values.shape[0] < 3:
                        values = np.concatenate([values, values[-1:]], axis=0)
                    return values
                def read_window(y, x, h, w):
                    return bands(dataset.read(indices, window=Window(x, y, w, h), masked=True))
                sample = bands(dataset.read(indices, out_shape=(len(indices), min(512, dataset.height), min(512, dataset.width)), masked=True, resampling=Resampling.nearest))
                probabilities = runner.predict_windows(read_window, dataset.height, dataset.width, sample)
                transform, crs = dataset.transform, dataset.crs
                source_metadata = {
                    "source_format": "geotiff",
                    "coordinate_reference": str(crs),
                    "geographic_bounds": list(transform_bounds(crs, "EPSG:4326", *dataset.bounds, densify_pts=21)),
                    "georeference_source": "embedded_geotiff",
                    "width": dataset.width,
                    "height": dataset.height,
                    "band_count": dataset.count,
                }
        except rasterio.errors.RasterioError as error:
            raise HTTPException(status_code=422, detail="The GeoTIFF could not be read.") from error
    source_metadata["inference"] = {
        "method": "overlapping_tiles", "tile_size": 256, "overlap": 64,
        "blending": "positive Hann weights", "normalization": "shared scene 2nd/98th percentiles from a sample up to 512x512",
        "nodata": "pixels invalid in any input band excluded", "pixel_limit": 16_777_216,
    }
    return _polygonize(probabilities, threshold, transform, crs, source_metadata, runner.model_metadata(), min_component_pixels)


def _read_raster(file_path: Path, bounds: tuple[float, float, float, float] | None):
    import numpy as np
    from PIL import Image
    from rasterio.transform import from_bounds

    suffix = file_path.suffix.lower()
    if suffix == ".png":
        with Image.open(file_path) as image:
            image.load()
            array = np.asarray(image.convert("RGB"), dtype=np.float32).transpose(2, 0, 1)
        height, width = array.shape[1:]
        evidence_metadata = KNOWN_PNG_EVIDENCE.get(_sha256(file_path))
        resolved_bounds = bounds
        georeference_source = "manual"
        if resolved_bounds is None and evidence_metadata is not None:
            resolved_bounds = evidence_metadata["bounds"]  # type: ignore[assignment]
            georeference_source = "trusted_evidence_manifest"
        if resolved_bounds:
            west, south, east, north = resolved_bounds
            if not _valid_bounds(resolved_bounds):
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="PNG bounds must be valid geographic coordinates with west < east and south < north.")
            transform = from_bounds(west, south, east, north, width, height)
            metadata = {
                "source_format": "png",
                "coordinate_reference": "EPSG:4326",
                "geographic_bounds": [west, south, east, north],
                "georeference_source": georeference_source,
                "width": width,
                "height": height,
                "band_count": 3,
            }
            if evidence_metadata is not None and georeference_source == "trusted_evidence_manifest":
                metadata.update({key: value for key, value in evidence_metadata.items() if key != "bounds"})
            return array, transform, "EPSG:4326", metadata
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This PNG has no embedded coordinates and is not in the trusted evidence registry. Open Advanced georeferencing and provide its geographic bounds, or upload a GeoTIFF.",
        )

    try:
        import rasterio
        from rasterio.warp import transform_bounds
        with rasterio.open(file_path) as dataset:
            if dataset.count == 0:
                raise ValueError("Raster has no bands.")
            indices = list(range(1, min(dataset.count, 3) + 1))
            array = dataset.read(indices, masked=True).filled(np.nan).astype(np.float32)
            while array.shape[0] < 3:
                array = np.concatenate([array, array[-1:, :, :]], axis=0)
            spatial_reference = str(dataset.crs) if dataset.crs else "image_pixels"
            geographic_bounds = None
            if dataset.crs:
                geographic_bounds = list(transform_bounds(dataset.crs, "EPSG:4326", *dataset.bounds, densify_pts=21))
            return array, dataset.transform, dataset.crs, {
                "source_format": "geotiff",
                "coordinate_reference": spatial_reference,
                "geographic_bounds": geographic_bounds,
                "georeference_source": "embedded_geotiff" if dataset.crs else "unavailable",
                "width": dataset.width,
                "height": dataset.height,
                "band_count": dataset.count,
            }
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The GeoTIFF cannot be read as a valid raster.") from error


def _polygonize(probabilities, threshold: float, transform, crs, source_metadata: dict[str, object], model_metadata: dict[str, object], min_component_pixels: int = 0):
    import numpy as np
    from rasterio.features import geometry_mask, shapes
    from rasterio.warp import transform_geom

    binary_mask = probabilities >= threshold
    raw_positive_count = int(binary_mask.sum())
    removed_components = 0
    if min_component_pixels > 1:
        from scipy.ndimage import label
        labels, _ = label(binary_mask)  # Four-neighbor connectivity matches polygonization.
        counts = np.bincount(labels.ravel())
        remove = counts < min_component_pixels
        remove[0] = False
        removed_components = int(remove[1:].sum())
        binary_mask[remove[labels]] = False
        del labels, counts, remove
    feature_collection: dict[str, object] = {"type": "FeatureCollection", "features": []}
    features: list[dict[str, object]] = []
    for geometry, value in shapes(binary_mask.astype(np.uint8), mask=binary_mask, transform=transform):
        if not value:
            continue
        if len(features) >= 10_000:
            raise HTTPException(status_code=422, detail="Segmentation exceeds 10,000 components. Crop the scene or raise the threshold.")
        # Rasterize each component only inside its pixel bounding window.
        from affine import Affine
        inverse = ~transform
        pixel_coordinates = [inverse * tuple(point) for ring in geometry["coordinates"] for point in ring]
        x0 = max(0, math.floor(min(point[0] for point in pixel_coordinates)))
        y0 = max(0, math.floor(min(point[1] for point in pixel_coordinates)))
        x1 = min(probabilities.shape[1], math.ceil(max(point[0] for point in pixel_coordinates)))
        y1 = min(probabilities.shape[0], math.ceil(max(point[1] for point in pixel_coordinates)))
        if x1 <= x0 or y1 <= y0:
            continue
        local_mask = geometry_mask([geometry], out_shape=(y1-y0, x1-x0), transform=transform * Affine.translation(x0, y0), invert=True)
        component_probability = probabilities[y0:y1, x0:x1][local_mask]
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
    from app.geospatial.metrics import calculate_spill_metrics
    try:
        metrics = calculate_spill_metrics(feature_collection)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    validation = {
        "geometry_metrics": metrics,
        "cleanup": {"min_component_pixels": min_component_pixels, "connectivity": 4, "removed_components": removed_components, "removed_pixels": raw_positive_count-int(binary_mask.sum()), "raw_positive_pixel_count": raw_positive_count},
        **source_metadata,
        "threshold": threshold,
        "positive_pixel_count": int(binary_mask.sum()),
        "component_count": len(features),
    }
    return feature_collection, model_metadata, validation


def _check_dimensions(width, height, png=False):
    limit = 4_194_304 if png else 16_777_216
    if width < 1 or height < 1 or width * height > limit:
        raise HTTPException(status_code=422, detail=f"Image exceeds the {limit:,}-pixel processing limit. Crop the scene or use a smaller image.")
