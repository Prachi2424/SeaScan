from __future__ import annotations

import json
from pathlib import Path

from fastapi import HTTPException, status

ENVIRONMENTAL_SUFFIXES = {".csv", ".geojson", ".json", ".nc", ".nc4"}
VELOCITY_ALIASES = {
    "current_u": {"current_u", "u_current", "u"},
    "current_v": {"current_v", "v_current", "v"},
    "wind_u": {"wind_u", "u_wind", "u10"},
    "wind_v": {"wind_v", "v_wind", "v10"},
}
COORDINATE_ALIASES = {
    "timestamp": {"time", "timestamp", "datetime", "date_time", "basedatetime"},
    "latitude": {"lat", "latitude"},
    "longitude": {"lon", "long", "longitude"},
}


def validate_environment_file(file_path: Path) -> dict[str, object]:
    suffix = file_path.suffix.lower()
    if suffix not in ENVIRONMENTAL_SUFFIXES:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Environmental evidence must be CSV, GeoJSON, JSON, NetCDF, or NC4.")
    if suffix == ".csv":
        return _validate_csv(file_path)
    if suffix in {".geojson", ".json"}:
        return _validate_geojson(file_path)
    return _validate_netcdf(file_path)


def _validate_csv(file_path: Path) -> dict[str, object]:
    try:
        import pandas as pd
        frame = pd.read_csv(file_path, nrows=50_000)
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Environmental CSV cannot be read.") from error
    if frame.empty:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Environmental CSV contains no rows.")
    columns = {str(column).lower().strip().replace(" ", "_"): str(column) for column in frame.columns}
    resolved = _resolve_velocities(columns)
    _assert_velocity_pair(resolved)
    coordinates = _resolve_coordinates(columns)
    _assert_coordinates(coordinates)
    return {"source_format": "csv", "inspected_row_count": int(len(frame)), "velocity_field_mapping": resolved, "coordinate_field_mapping": coordinates, "columns": list(frame.columns)}


def _validate_geojson(file_path: Path) -> dict[str, object]:
    try:
        document = json.loads(file_path.read_text(encoding="utf-8"))
        features = document.get("features", [])
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Environmental GeoJSON is invalid.") from error
    if document.get("type") != "FeatureCollection" or not isinstance(features, list) or not features:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Environmental GeoJSON must be a non-empty FeatureCollection.")
    properties = features[0].get("properties") or {}
    columns = {str(key).lower().strip().replace(" ", "_"): str(key) for key in properties}
    resolved = _resolve_velocities(columns)
    _assert_velocity_pair(resolved)
    coordinates = _resolve_coordinates(columns)
    if "timestamp" not in coordinates:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Environmental GeoJSON feature properties require a timestamp field.")
    return {"source_format": "geojson", "feature_count": len(features), "velocity_field_mapping": resolved, "coordinate_field_mapping": coordinates}


def _validate_netcdf(file_path: Path) -> dict[str, object]:
    try:
        import xarray as xr
        with xr.open_dataset(file_path) as dataset:
            variables = list(dataset.data_vars)
            columns = {name.lower().strip().replace(" ", "_"): name for name in variables}
            resolved = _resolve_velocities(columns)
            _assert_velocity_pair(resolved)
            coordinates = _resolve_coordinates({name.lower(): name for name in [*dataset.coords, *dataset.data_vars]})
            if "timestamp" not in coordinates or "latitude" not in coordinates or "longitude" not in coordinates:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Environmental NetCDF requires time, latitude, and longitude coordinate variables.")
            dimensions = {str(key): int(value) for key, value in dataset.sizes.items()}
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Environmental NetCDF cannot be opened.") from error
    return {"source_format": "netcdf", "velocity_field_mapping": resolved, "coordinate_field_mapping": coordinates, "data_variables": variables, "dimensions": dimensions}


def _resolve_velocities(columns: dict[str, str]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for canonical, aliases in VELOCITY_ALIASES.items():
        matched = next((columns[alias] for alias in aliases if alias in columns), None)
        if matched:
            resolved[canonical] = matched
    return resolved


def _assert_velocity_pair(resolved: dict[str, str]) -> None:
    has_current = {"current_u", "current_v"}.issubset(resolved)
    has_wind = {"wind_u", "wind_v"}.issubset(resolved)
    if not has_current and not has_wind:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Environmental data needs both components of a current vector or wind vector.")


def _resolve_coordinates(columns: dict[str, str]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for canonical, aliases in COORDINATE_ALIASES.items():
        match = next((columns[alias] for alias in aliases if alias in columns), None)
        if match:
            resolved[canonical] = match
    return resolved


def _assert_coordinates(resolved: dict[str, str]) -> None:
    missing = {"timestamp", "latitude", "longitude"}.difference(resolved)
    if missing:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Environmental CSV is missing required coordinate field(s): {', '.join(sorted(missing))}.")
