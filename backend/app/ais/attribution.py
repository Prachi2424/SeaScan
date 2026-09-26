from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from fastapi import HTTPException, status

SCORE_WEIGHTS = {"proximity": 0.30, "temporal": 0.25, "trajectory": 0.20, "behavioral_anomaly": 0.10, "vessel_type": 0.05, "ais_consistency": 0.10}


def rank_candidates(file_path: Path, metadata: dict[str, object], *, origin_latitude: float, origin_longitude: float, estimated_origin_at, search_radius_km: float, temporal_window_minutes: int, behavior_window_hours: int, origin_region=None, release_heading=None, exclusions=None):
    import math
    import numpy as np
    import pandas as pd
    from pyproj import CRS, Transformer
    from shapely.geometry import Point, LineString, shape
    from shapely.ops import transform

    fields = metadata.get("field_mapping")
    if not isinstance(fields, dict):
        raise HTTPException(status_code=422, detail="AIS asset lacks field mapping metadata.")
    try:
        frame = pd.read_csv(file_path) if file_path.suffix.lower()==".csv" else pd.read_parquet(file_path)
    except Exception as error:
        raise HTTPException(status_code=422, detail="AIS evidence cannot be read.") from error
    canonical = _canonicalise(frame, fields).sort_values("timestamp").drop_duplicates(["mmsi","timestamp"])
    event = pd.Timestamp(estimated_origin_at)
    event = event.tz_localize("UTC") if event.tzinfo is None else event.tz_convert("UTC")
    low, high = event-pd.Timedelta(minutes=temporal_window_minutes), event+pd.Timedelta(minutes=temporal_window_minutes)
    projection = Transformer.from_crs("EPSG:4326", CRS.from_proj4(f"+proj=aeqd +lat_0={origin_latitude} +lon_0={origin_longitude} +datum=WGS84 +units=m"), always_xy=True)
    region = transform(projection.transform,shape(origin_region["geometry"])) if origin_region else None
    candidates = []
    for mmsi, vessel in canonical.groupby("mmsi"):
        margin = max(behavior_window_hours*60, temporal_window_minutes+60)
        history = vessel[vessel.timestamp.between(event-pd.Timedelta(minutes=margin),event+pd.Timedelta(minutes=margin))].copy()
        local = history[history.timestamp.between(low,high)]
        points = []
        intersects = False
        skipped = 0
        for row in local.itertuples():
            x,y = projection.transform(row.longitude,row.latitude)
            if not np.isfinite([x,y]).all(): continue
            points.append((math.hypot(x,y)/1000,abs((row.timestamp-event).total_seconds()),row.timestamp,False,None))
            if region is not None and region.covers(Point(x,y)): intersects=True
        rows = list(history.itertuples())
        for first, second in zip(rows,rows[1:]):
            seconds = (second.timestamp-first.timestamp).total_seconds()
            if second.timestamp < low or first.timestamp > high or seconds <= 0: continue
            x1,y1 = projection.transform(first.longitude,first.latitude)
            x2,y2 = projection.transform(second.longitude,second.latitude)
            if not np.isfinite([x1,y1,x2,y2]).all():
                skipped += 1
                continue
            distance = math.hypot(x2-x1,y2-y1)
            if seconds>3600 or distance/seconds/0.514444>60:
                skipped += 1
                continue
            lo=max(0,(low-first.timestamp).total_seconds()/seconds)
            hi=min(1,(high-first.timestamp).total_seconds()/seconds)
            vx,vy=x2-x1,y2-y1
            fraction=float(np.clip(-(x1*vx+y1*vy)/(distance**2),lo,hi)) if distance else float(np.clip((event-first.timestamp).total_seconds()/seconds,lo,hi))
            t=first.timestamp+pd.Timedelta(seconds=seconds*fraction)
            heading=math.degrees(math.atan2(vx,vy))%360 if distance>1 else None
            points.append((math.hypot(x1+fraction*vx,y1+fraction*vy)/1000,abs((t-event).total_seconds()),t,True,heading))
            if region is not None:
                segment=LineString([(x1+lo*vx,y1+lo*vy),(x1+hi*vx,y1+hi*vy)]) if distance else Point(x1,y1)
                intersects |= region.intersects(segment)
        if not points:
            reason="No observed positions or supported interpolated segments in the time window."
        else:
            closest=min(points,key=lambda item:(item[0],item[1]))
            reason=None if closest[0]<=search_radius_km or intersects else "Outside search radius and any supplied hindcast region."
        if reason:
            if exclusions is not None: exclusions.append({"mmsi":str(int(mmsi)),"reason":reason,"unsupported_segments":skipped})
            continue
        minimum,delta,when,interpolated,heading=closest
        proximity=max(0,1-minimum/search_radius_km)
        temporal=max(0,1-delta/(temporal_window_minutes*60))
        alignment=None if heading is None or release_heading is None else (1+math.cos(math.radians(heading-release_heading)))/2
        trajectory_parts=([float(intersects)] if region is not None else [])+([alignment] if alignment is not None else [])
        trajectory=sum(trajectory_parts)/len(trajectory_parts) if trajectory_parts else 0.0
        behavior_history=vessel[vessel.timestamp.between(event-pd.Timedelta(hours=behavior_window_hours),event+pd.Timedelta(hours=behavior_window_hours))]
        behavior,behavior_evidence=_behavior_features(behavior_history)
        consistency,maximum_gap=_ais_consistency(history)
        vessel_type=str(history.vessel_type.dropna().iloc[0]) if history.vessel_type.notna().any() else None
        breakdown=dict(proximity=proximity,temporal=temporal,trajectory=trajectory,behavioral_anomaly=behavior,vessel_type=_vessel_type_score(vessel_type),ais_consistency=consistency)
        breakdown={key:round(value,6) for key,value in breakdown.items()}
        coords=[[float(row.longitude),float(row.latitude)] for row in rows]
        track_distances = _haversine(history.latitude.to_numpy(), history.longitude.to_numpy(), origin_latitude, origin_longitude)
        positions = [{
            "timestamp": row.timestamp.isoformat(),
            "latitude": float(row.latitude),
            "longitude": float(row.longitude),
            "distance_to_origin_km": round(float(distance), 4),
            "speed_knots": None if not np.isfinite(row.speed_knots) else round(float(row.speed_knots), 3),
            "course_degrees": None if not np.isfinite(row.course_degrees) else round(float(row.course_degrees), 3),
        } for row, distance in zip(history.itertuples(), track_distances, strict=True)]
        warnings=[]
        if skipped: warnings.append(f"{skipped} segment(s) not interpolated: gap over 60 minutes, implied speed over 60 knots or invalid projected coordinates.")
        if not trajectory_parts: warnings.append("No hindcast region/heading supplied; trajectory component has no supporting evidence and contributes zero.")
        if maximum_gap is None: warnings.append("Only one AIS observation; continuity cannot be assessed.")
        candidates.append({"mmsi":str(int(mmsi)),"vessel_type":vessel_type,"evidence_score":round(sum(breakdown[key]*SCORE_WEIGHTS[key] for key in SCORE_WEIGHTS),6),"score_breakdown":breakdown,
            "evidence":{"closest_approach_distance_km":round(minimum,4),"closest_observed_distance_km":round(min(point[0] for point in points if not point[3]),4) if len(local) else None,"closest_approach_at":when.isoformat(),"closest_approach_interpolated":interpolated,"time_offset_minutes":round(delta/60,3),"origin_region_intersection":bool(intersects) if region is not None else None,"heading_alignment":alignment,"positions_in_time_window":len(local),"behavior":behavior_evidence,"maximum_ais_gap_minutes":maximum_gap,"warnings":warnings,"score_note":"Fixed-weight investigative priority, not a calibrated probability. Missing features contribute zero. Heading follows approximate drift direction, not proof of discharge."},
            "track_geojson":{"type":"Feature","geometry":{"type":"LineString","coordinates":coords} if len(coords)>1 else {"type":"Point","coordinates":coords[0]},"properties":{"mmsi":str(int(mmsi)),"position_count":len(coords),"positions":positions}}})
    return sorted(candidates,key=lambda candidate:(-candidate["evidence_score"],candidate["mmsi"]))


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
    result["vessel_type"] = frame[vessel_column].astype("string") if vessel_column else None
    result = result.dropna(subset=["mmsi", "timestamp", "latitude", "longitude"])
    return result[result.latitude.between(-90, 90) & result.longitude.between(-180, 180)].copy()


def _behavior_features(history):
    import numpy as np
    speeds=history.speed_knots.where(history.speed_knots.between(0,102.1)).dropna()
    gaps=history.timestamp.diff().dt.total_seconds().dropna()/60
    speed_drop=bool(((history.speed_knots.shift(1)>=5)&(history.speed_knots.between(0,1,inclusive="left"))&(history.timestamp.diff().dt.total_seconds()<=3600)).any()) if len(speeds)>=2 else None
    loitering=None
    duration=(history.timestamp.max()-history.timestamp.min()).total_seconds()/60 if len(history)>1 else 0
    if len(history)>=6 and duration>=30:
        distances=_haversine(history.latitude.to_numpy(),history.longitude.to_numpy(),float(history.latitude.iloc[0]),float(history.longitude.iloc[0]))
        loitering=bool(max(distances)<.5 and not (gaps>30).any())
    courses=history.course_degrees.where(history.course_degrees.between(0,359.999))
    differences=abs((courses.diff()+180)%360-180)
    course_change=bool(((differences>=60)&(history.timestamp.diff().dt.total_seconds()<=1800)&(history.speed_knots>=2)&(history.speed_knots.shift(1)>=2)).any()) if courses.notna().sum()>=2 and len(speeds)>=2 else None
    gap=bool((gaps>60).any()) if len(gaps) else None
    score=sum(float(value) for value in [speed_drop,loitering,course_change,gap] if value is not None)/4
    return score,{"speed_drop":speed_drop,"loitering":loitering,"course_change":course_change,"ais_gap_over_60_minutes":gap,"median_speed_knots":float(speeds.median()) if len(speeds) else None,"note":"Heuristic indicators; gaps do not establish deliberate switch-off or spoofing."}


def _ais_consistency(history):
    if len(history)<2: return 0.0,None
    maximum=float((history.timestamp.diff().dt.total_seconds().dropna()/60).max())
    return max(0,1-maximum/360),round(maximum,3)


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
    return 6371.0088 * 2 * np.arcsin(np.sqrt(np.clip(value,0,1)))
