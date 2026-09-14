from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from fastapi import HTTPException, status


def load_environment_observations(file_path: Path, metadata: dict[str, object]):
    """Load real point observations into a canonical time/position/velocity frame."""
    import pandas as pd

    source_format = metadata.get("source_format")
    velocity_fields = metadata.get("velocity_field_mapping")
    coordinate_fields = metadata.get("coordinate_field_mapping")
    if not isinstance(velocity_fields, dict) or not isinstance(coordinate_fields, dict):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Environmental asset lacks validated field metadata.")
    if source_format == "csv":
        frame = pd.read_csv(file_path)
    elif source_format == "geojson":
        import json
        document = json.loads(file_path.read_text(encoding="utf-8"))
        rows = []
        for feature in document["features"]:
            coordinates = (feature.get("geometry") or {}).get("coordinates")
            properties = feature.get("properties") or {}
            if not isinstance(coordinates, list) or len(coordinates) < 2:
                continue
            row = dict(properties)
            row[coordinate_fields["longitude"]] = coordinates[0]
            row[coordinate_fields["latitude"]] = coordinates[1]
            rows.append(row)
        frame = pd.DataFrame(rows)
    elif source_format == "netcdf":
        try:
            import xarray as xr
            selected = [*velocity_fields.values()]
            with xr.open_dataset(file_path) as dataset:
                frame = dataset[selected].to_dataframe().reset_index()
        except Exception as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Environmental NetCDF cannot be converted to timestamped vector observations.") from error
    else:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported environmental source format.")
    canonical = pd.DataFrame({
        "timestamp": pd.to_datetime(frame[coordinate_fields["timestamp"]], utc=True, errors="coerce"),
        "latitude": pd.to_numeric(frame[coordinate_fields["latitude"]], errors="coerce"),
        "longitude": pd.to_numeric(frame[coordinate_fields["longitude"]], errors="coerce"),
        "current_u": pd.to_numeric(frame[velocity_fields["current_u"]], errors="coerce") if "current_u" in velocity_fields else 0.0,
        "current_v": pd.to_numeric(frame[velocity_fields["current_v"]], errors="coerce") if "current_v" in velocity_fields else 0.0,
        "wind_u": pd.to_numeric(frame[velocity_fields["wind_u"]], errors="coerce") if "wind_u" in velocity_fields else 0.0,
        "wind_v": pd.to_numeric(frame[velocity_fields["wind_v"]], errors="coerce") if "wind_v" in velocity_fields else 0.0,
    }).dropna(subset=["timestamp", "latitude", "longitude", "current_u", "current_v", "wind_u", "wind_v"])
    canonical = canonical[canonical.latitude.between(-90, 90) & canonical.longitude.between(-180, 180)]
    if canonical.empty:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Environmental asset has no valid timestamped vector observations.")
    return canonical.reset_index(drop=True)


def simulate_particles(observations, *, latitude: float, longitude: float, observed_at, duration_hours: float, step_minutes: int, particle_count: int, initial_spread_meters: float, windage_factor: float, direction: int, random_seed: int):
    """Advect particles with observed current plus windage; direction -1 creates a hindcast."""
    import numpy as np
    import pandas as pd
    from shapely.geometry import MultiPoint, mapping

    start_time = pd.Timestamp(observed_at)
    if start_time.tzinfo is None:
        start_time = start_time.tz_localize("UTC")
    else:
        start_time = start_time.tz_convert("UTC")
    steps = round(duration_hours * 60 / step_minutes)
    rng = np.random.default_rng(random_seed)
    north_offsets = rng.normal(0, initial_spread_meters, particle_count)
    east_offsets = rng.normal(0, initial_spread_meters, particle_count)
    latitudes = latitude + north_offsets / 111_320
    longitudes = longitude + east_offsets / (111_320 * np.cos(np.radians(latitude)))
    trajectory_features = []
    sampling_gaps: list[float] = []
    dt_seconds = step_minutes * 60 * direction
    for step in range(steps + 1):
        timestamp = start_time + timedelta(minutes=step * step_minutes * direction)
        mean_latitude, mean_longitude = float(latitudes.mean()), float(longitudes.mean())
        velocity, time_gap_minutes = _nearest_velocity(observations, timestamp, mean_latitude, mean_longitude)
        sampling_gaps.append(time_gap_minutes)
        if time_gap_minutes > 360:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Environmental observations are more than six hours from a requested drift step; SeaScan will not extrapolate the field silently.")
        if step < steps:
            east_velocity = velocity[0] + windage_factor * velocity[2]
            north_velocity = velocity[1] + windage_factor * velocity[3]
            latitudes = latitudes + (north_velocity * dt_seconds / 111_320)
            longitudes = longitudes + (east_velocity * dt_seconds / (111_320 * np.cos(np.radians(latitudes))))
        trajectory_features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [mean_longitude, mean_latitude]}, "properties": {"timestamp": timestamp.isoformat(), "current_u_mps": velocity[0], "current_v_mps": velocity[1], "wind_u_mps": velocity[2], "wind_v_mps": velocity[3]}})
    final_points = [(float(lon), float(lat)) for lat, lon in zip(latitudes, longitudes, strict=True)]
    hull = MultiPoint(final_points).convex_hull
    if hull.geom_type == "Point":
        hull = hull.buffer(0.00001)
    elif hull.geom_type == "LineString":
        hull = hull.buffer(0.00001)
    return {
        "trajectory": {"type": "FeatureCollection", "features": trajectory_features},
        "probability_region": {"type": "Feature", "geometry": mapping(hull), "properties": {"particle_count": particle_count, "interpretation": "convex envelope of final particle locations; not a legal or probabilistic certainty"}},
        "sampling": {"method": "nearest timestamped environmental observation to ensemble mean position", "maximum_time_gap_minutes": round(max(sampling_gaps), 3), "step_minutes": step_minutes, "windage_factor": windage_factor},
    }


def _nearest_velocity(observations, timestamp, latitude: float, longitude: float):
    import numpy as np
    time_deltas = (observations.timestamp - timestamp).abs().dt.total_seconds().to_numpy() / 60
    spatial = (observations.latitude.to_numpy() - latitude) ** 2 + (observations.longitude.to_numpy() - longitude) ** 2
    index = int(np.argmin(time_deltas * 0.02 + spatial))
    row = observations.iloc[index]
    return (float(row.current_u), float(row.current_v), float(row.wind_u), float(row.wind_v)), float(time_deltas[index])
