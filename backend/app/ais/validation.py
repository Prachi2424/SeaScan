from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, status

AIS_SUFFIXES = {".csv", ".parquet"}
FIELD_ALIASES = {
    "mmsi": {"mmsi", "mmsi_number"},
    "timestamp": {"basedatetime", "timestamp", "time", "datetime", "date_time_utc"},
    "latitude": {"lat", "latitude"},
    "longitude": {"lon", "long", "longitude"},
    "speed_knots": {"sog", "speed", "speed_over_ground"},
    "course_degrees": {"cog", "course", "course_over_ground"},
}


def validate_ais_file(file_path: Path) -> dict[str, object]:
    """Inspect a real AIS file and verify its identity/time/location fields without modifying it."""
    if file_path.suffix.lower() not in AIS_SUFFIXES:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="AIS evidence must be CSV or Parquet.")
    try:
        import pandas as pd
        if file_path.suffix.lower() == ".csv":
            frame = pd.read_csv(file_path, nrows=50_000)
        else:
            frame = pd.read_parquet(file_path)
            if len(frame) > 50_000:
                frame = frame.head(50_000)
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The AIS file cannot be read as the declared format.") from error
    if frame.empty:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="AIS evidence contains no rows.")
    resolved = _resolve_fields([str(column) for column in frame.columns])
    missing = [field for field in ("mmsi", "timestamp", "latitude", "longitude") if field not in resolved]
    if missing:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"AIS file is missing required field(s): {', '.join(missing)}.")
    timestamp = pd.to_datetime(frame[resolved["timestamp"]], utc=True, errors="coerce")
    latitude = pd.to_numeric(frame[resolved["latitude"]], errors="coerce")
    longitude = pd.to_numeric(frame[resolved["longitude"]], errors="coerce")
    mmsi = pd.to_numeric(frame[resolved["mmsi"]], errors="coerce")
    valid_rows = timestamp.notna() & latitude.between(-90, 90) & longitude.between(-180, 180) & mmsi.between(100_000_000, 999_999_999)
    valid_count = int(valid_rows.sum())
    if valid_count == 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No AIS rows contain a valid MMSI, UTC timestamp, latitude, and longitude.")
    valid_timestamps = timestamp[valid_rows]
    return {
        "source_format": file_path.suffix.lower().removeprefix("."),
        "inspected_row_count": int(len(frame)),
        "valid_position_count": valid_count,
        "field_mapping": resolved,
        "time_start_utc": valid_timestamps.min().isoformat(),
        "time_end_utc": valid_timestamps.max().isoformat(),
    }


def _resolve_fields(columns: list[str]) -> dict[str, str]:
    normalised = {column.lower().strip().replace(" ", "_"): column for column in columns}
    result: dict[str, str] = {}
    for canonical, aliases in FIELD_ALIASES.items():
        match = next((normalised[alias] for alias in aliases if alias in normalised), None)
        if match:
            result[canonical] = match
    return result
