from pathlib import Path

import numpy as np
import pytest
from fastapi import HTTPException
from PIL import Image

from app.geospatial.satellite import _polygonize, _read_raster


BOUNDS = (-88.8509434, 29.0606100, -88.4597525, 29.2801243)


@pytest.fixture
def scene(tmp_path):
    path = tmp_path / "scene.png"
    Image.new("RGB", (256, 256)).save(path)
    return path


def test_png_transform_maps_pixels_to_geographic_bounds(scene):
    raster, transform, crs, metadata = _read_raster(scene, BOUNDS)
    west, south, east, north = BOUNDS
    assert raster.shape == (3, 256, 256)
    assert crs == "EPSG:4326"
    assert metadata["coordinate_reference"] == "EPSG:4326"
    assert transform * (0, 0) == pytest.approx((west, north))
    assert transform * (256, 256) == pytest.approx((east, south))
    assert transform * (128, 128) == pytest.approx(((west + east) / 2, (south + north) / 2))


def test_polygonized_png_stays_inside_geographic_bounds(scene):
    _, transform, crs, metadata = _read_raster(scene, BOUNDS)
    probabilities = np.zeros((256, 256), dtype=np.float32)
    probabilities[80:120, 90:140] = 0.8
    geojson, _, validation = _polygonize(probabilities, 0.5, transform, crs, metadata, {})
    assert validation["component_count"] == 1
    west, south, east, north = BOUNDS
    for longitude, latitude in geojson["features"][0]["geometry"]["coordinates"][0]:
        assert west <= longitude <= east
        assert south <= latitude <= north


def test_registered_demo_png_is_georeferenced_automatically():
    path = Path(__file__).parents[2] / "demo" / "evidence" / "satellite" / "sentinel1_2018_12_19_e.png"
    raster, transform, crs, metadata = _read_raster(path, None)
    west, south, east, north = BOUNDS
    assert raster.shape == (3, 256, 256)
    assert crs == "EPSG:4326"
    assert metadata["georeference_source"] == "trusted_evidence_manifest"
    assert metadata["geographic_bounds"] == list(BOUNDS)
    assert metadata["acquired_at"] == "2018-12-19T12:00:00Z"
    assert transform * (0, 0) == pytest.approx((west, north))
    assert transform * (256, 256) == pytest.approx((east, south))


@pytest.mark.parametrize("bounds", [None, (-88, 29, -89, 30), (-88, 29, -87, 100), (float("nan"), 29, -87, 30)])
def test_png_rejects_missing_or_invalid_geographic_bounds(scene, bounds):
    with pytest.raises(HTTPException) as error:
        _read_raster(scene, bounds)
    assert error.value.status_code == 422
