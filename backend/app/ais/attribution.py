from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from fastapi import HTTPException, status

SCORE_WEIGHTS = {"proximity": 0.30, "temporal": 0.25, "trajectory": 0.20, "behavioral_anomaly": 0.10, "vessel_type": 0.05, "ais_consistency": 0.10}


def rank_candidates(file_path: Path, metadata: dict[str, object], *, origin_latitude: float, origin_longitude: float, estimated_origin_at, search_radius_km: float, temporal_window_minutes: int, behavior_window_hours: int):
    import numpy as np
    import pandas as pd

    fields = metadata.get("field_mapping")
    if not isinstance(fields, dict):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="AIS asset lacks validated field mapping metadata.")
    try:
        frame = pd.read_csv(file_path) if file_path.suffix.lower() == ".csv" else pd.read_parquet(file_path)
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="AIS evidence can no longer be read.") from error
    canonical = _canonicalise(frame, fields)
    event_time = pd.Timestamp(estimated_origin_at)
    event_time = event_time.tz_localize("UTC") if event_time.tzinfo is None else event_time.tz_convert("UTC")
    window = timedelta(minutes=temporal_window_minutes)
    candidate_window = canonical[canonical.timestamp.between(event_time - window, event_time + window)].copy()
    if candidate_window.empty:
        return []
    candidate_window["distance_km"] = _haversine(candidate_window.latitude.to_numpy(), candidate_window.longitude.to_numpy(), origin_latitude, origin_longitude)
    candidate_ids = candidate_window.loc[candidate_window.distance_km <= search_radius_km, "mmsi"].unique()
    candidates = []
    behavior_window = timedelta(hours=behavior_window_hours)
    for mmsi in candidate_ids:
        local = candidate_window[candidate_window.mmsi == mmsi].copy()
        history = canonical[(canonical.mmsi == mmsi) & canonical.timestamp.between(event_time - behavior_window, event_time + behavior_window)].sort_values("timestamp")
        candidates.append(_score_vessel(local, history, origin_latitude, origin_longitude, search_radius_km, temporal_window_minutes))
    return sorted(candidates, key=lambda candidate: candidate["evidence_score"], reverse=True)


def _canonicalise(frame, fields: dict[str, str]):
    import pandas as pd
    result = pd.DataFrame({
        "mmsi": pd.to_numeric(frame[fields["mmsi"]], errors="coerce").astype("Int64"),
        "timestamp": pd.to_datetime(frame[fields["timestamp"]], utc=True, errors="coerce"),
        "latitude": pd.to_numeric(frame[fields["latitude"]], errors="coerce"),
        "longitude": pd.to_numeric(frame[fields["longitude"]], errors="coerce"),
        "speed_knots": pd.to_numeric(frame[fields["speed_knots"]], errors="coerce") if "speed_knots" in fields else float("nan"),
        "course_degrees": pd.to_numeric(frame[fields["course_degrees"]], errors="coerce") if "course_degrees" in fields else float("nan"),
    })
    vessel_column = next((column for column in frame.columns if str(column).lower().replace(" ", "_") in {"vesseltype", "vessel_type", "shiptype", "ship_type"}), None)
    result["vessel_type"] = frame[vessel_column].astype(str) if vessel_column else None
    result = result.dropna(subset=["mmsi", "timestamp", "latitude", "longitude"])
    return result[result.latitude.between(-90, 90) & result.longitude.between(-180, 180)].copy()


def _score_vessel(local, history, origin_latitude: float, origin_longitude: float, radius_km: float, window_minutes: int):
    import numpy as np
    minimum_distance = float(local.distance_km.min())
    proximity = max(0.0, 1 - minimum_distance / radius_km)
    temporal = min(1.0, len(local) / max(1, window_minutes / 10))
    distances = _haversine(history.latitude.to_numpy(), history.longitude.to_numpy(), origin_latitude, origin_longitude)
    trajectory = max(0.0, min(1.0, (float(distances.max()) - float(distances.min())) / radius_km)) if len(history) > 1 else 0.0
    behavior, behavior_evidence = _behavior_features(history)
    vessel_type = str(local.vessel_type.dropna().iloc[0]) if local.vessel_type.notna().any() else None
    vessel_type_score = _vessel_type_score(vessel_type)
    consistency, maximum_gap = _ais_consistency(history)
    breakdown = {"proximity": round(proximity, 6), "temporal": round(temporal, 6), "trajectory": round(trajectory, 6), "behavioral_anomaly": round(behavior, 6), "vessel_type": round(vessel_type_score, 6), "ais_consistency": round(consistency, 6)}
    total = sum(breakdown[key] * SCORE_WEIGHTS[key] for key in SCORE_WEIGHTS)
    coordinates = [[float(row.longitude), float(row.latitude)] for row in history.itertuples()]
    geometry = {"type": "LineString", "coordinates": coordinates} if len(coordinates) > 1 else {"type": "Point", "coordinates": coordinates[0]}
    return {"mmsi": str(int(local.mmsi.iloc[0])), "vessel_type": vessel_type, "evidence_score": round(total, 6), "score_breakdown": breakdown, "evidence": {"closest_observed_distance_km": round(minimum_distance, 4), "positions_in_time_window": int(len(local)), "behavior": behavior_evidence, "maximum_ais_gap_minutes": round(maximum_gap, 3), "score_note": "Evidence-weighted prioritization only. It is not a legal determination of responsibility."}, "track_geojson": {"type": "Feature", "geometry": geometry, "properties": {"mmsi": str(int(local.mmsi.iloc[0])), "position_count": len(coordinates)}}}


def _behavior_features(history):
    import numpy as np
    if history.empty or history.speed_knots.notna().sum() < 2:
        return 0.0, {"speed_drop": None, "loitering": None, "ais_gap": None, "reason": "SOG was not present in the real AIS export."}
    speeds = history.speed_knots.dropna()
    median_speed = float(speeds.median())
    speed_drop = median_speed >= 5 and bool((speeds < 1).any())
    latitude_span = float(history.latitude.max() - history.latitude.min()) * 111.32
    longitude_span = float(history.longitude.max() - history.longitude.min()) * 111.32
    loitering = len(history) >= 6 and max(latitude_span, longitude_span) < 0.5
    gaps = history.timestamp.sort_values().diff().dt.total_seconds().dropna() / 60
    gap = bool((gaps > 60).any())
    score = (float(speed_drop) + float(loitering) + float(gap)) / 3
    return score, {"speed_drop": speed_drop, "loitering": loitering, "ais_gap_over_60_minutes": gap, "median_speed_knots": round(median_speed, 3)}


def _ais_consistency(history):
    if len(history) < 2:
        return 0.0, float("inf")
    gaps = history.timestamp.sort_values().diff().dt.total_seconds().dropna() / 60
    maximum_gap = float(gaps.max())
    return max(0.0, 1 - maximum_gap / 360), maximum_gap


def _vessel_type_score(vessel_type: str | None) -> float:
    if not vessel_type:
        return 0.0
    normalized = vessel_type.lower()
    if "tanker" in normalized or normalized in {"80", "81", "82", "83", "84", "85", "86", "87", "88", "89"}:
        return 1.0
    if "cargo" in normalized or normalized.startswith("7"):
        return 0.5
    return 0.0


def _haversine(latitudes, longitudes, target_latitude: float, target_longitude: float):
    import numpy as np
    latitude_1, longitude_1, latitude_2, longitude_2 = map(np.radians, [latitudes, longitudes, target_latitude, target_longitude])
    delta_latitude, delta_longitude = latitude_2 - latitude_1, longitude_2 - longitude_1
    value = np.sin(delta_latitude / 2) ** 2 + np.cos(latitude_1) * np.cos(latitude_2) * np.sin(delta_longitude / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(value))
