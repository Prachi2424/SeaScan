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
    import numpy as np
    canonical = canonical[np.isfinite(canonical[["current_u", "current_v", "wind_u", "wind_v"]]).all(axis=1)]
    if canonical.empty:
        raise HTTPException(status_code=422, detail="Environmental observations have no finite velocities.")
    canonical = canonical.reset_index(drop=True)
    canonical.attrs["warnings"] = []
    if "wind_u" not in velocity_fields or "wind_v" not in velocity_fields:
        canonical.attrs["warnings"].append("Wind components were not provided; missing wind components treated as zero.")
    if "current_u" not in velocity_fields or "current_v" not in velocity_fields:
        canonical.attrs["warnings"].append("Current components were not provided; missing current components treated as zero.")
    return canonical


class EnvironmentalField:
    """Four-neighbor inverse-distance interpolation on a sphere, then linear time interpolation."""
    def __init__(self, observations):
        import numpy as np
        import pandas as pd
        from scipy.spatial import cKDTree
        self.frames = []
        self.times = []
        self.maximum_distance_km = 0.0
        self.maximum_time_gap_minutes = 0.0
        self.warnings = set(observations.attrs.get("warnings", []))
        for timestamp, frame in observations.groupby("timestamp", sort=True):
            frame = frame.groupby(["latitude", "longitude"], as_index=False)[["current_u", "current_v", "wind_u", "wind_v"]].mean()
            values = frame[["current_u", "current_v", "wind_u", "wind_v"]].to_numpy(dtype=float)
            if not np.isfinite(values).all():
                raise HTTPException(status_code=422, detail="Environmental velocities must be finite.")
            xyz = self.xyz(frame.latitude.to_numpy(), frame.longitude.to_numpy())
            self.times.append(pd.Timestamp(timestamp).value / 1e9)
            self.frames.append((cKDTree(xyz), values))
        self.times = np.asarray(self.times)
        if not len(self.times):
            raise HTTPException(status_code=422, detail="Environmental observations are empty.")

    @staticmethod
    def xyz(latitudes, longitudes):
        import numpy as np
        lat, lon = np.radians(latitudes), np.radians(longitudes)
        return np.column_stack((np.cos(lat)*np.cos(lon), np.cos(lat)*np.sin(lon), np.sin(lat)))

    def spatial(self, index, latitudes, longitudes):
        import numpy as np
        tree, values = self.frames[index]
        distances, indices = tree.query(self.xyz(latitudes, longitudes), k=min(4, len(values)))
        if distances.ndim == 1:
            distances, indices = distances[:,None], indices[:,None]
        km = 6371.0088 * 2 * np.arcsin(np.clip(distances / 2, 0, 1))
        nearest = km[:,0]
        self.maximum_distance_km = max(self.maximum_distance_km, float(nearest.max()))
        if (nearest > 100).any():
            raise HTTPException(status_code=422, detail="A drift particle is more than 100 km from environmental observations. Upload wider regional coverage or shorten the simulation.")
        if len(values) < 3:
            self.warnings.add("Sparse spatial coverage: fewer than three distinct locations at one or more timestamps.")
        if (nearest > 25).any():
            self.warnings.add("Some particles are over 25 km from environmental observations; spatial estimates are weakly supported.")
        weights = np.where(km <= 100, 1 / np.maximum(km, 1e-6)**2, 0)
        exact = km[:,0] < 1e-6
        weights[exact] = 0
        weights[exact,0] = 1
        weights /= weights.sum(axis=1, keepdims=True)
        return (values[indices] * weights[:,:,None]).sum(axis=1)

    def velocity(self, timestamp, latitudes, longitudes):
        import numpy as np
        import pandas as pd
        t = pd.Timestamp(timestamp).value / 1e9
        right = int(np.searchsorted(self.times, t))
        if right < len(self.times) and self.times[right] == t:
            return self.spatial(right, latitudes, longitudes)
        if right == 0 or right == len(self.times):
            index = 0 if right == 0 else len(self.times)-1
            gap = abs(t-self.times[index])/60
            self.maximum_time_gap_minutes = max(self.maximum_time_gap_minutes, gap)
            if gap > 360:
                raise HTTPException(status_code=422, detail="Environmental time coverage ends more than six hours from a drift step. Upload matching observations or shorten the simulation.")
            self.warnings.add("Outside observation time coverage: nearest boundary field held constant for up to six hours; this is not temporal interpolation.")
            return self.spatial(index, latitudes, longitudes)
        left = right-1
        span = (self.times[right]-self.times[left])/60
        if span > 360:
            raise HTTPException(status_code=422, detail="Environmental timestamps have a gap exceeding six hours; interpolation is not supported across this gap.")
        self.maximum_time_gap_minutes = max(self.maximum_time_gap_minutes, (t-self.times[left])/60, (self.times[right]-t)/60)
        fraction = (t-self.times[left])/(self.times[right]-self.times[left])
        return (1-fraction)*self.spatial(left,latitudes,longitudes) + fraction*self.spatial(right,latitudes,longitudes)


def simulate_particles(observations, *, latitude: float, longitude: float, observed_at, duration_hours: float, step_minutes: int, particle_count: int, initial_spread_meters: float, windage_factor: float, direction: int, random_seed: int):
    """Per-particle midpoint advection; negative time advances perform approximate hindcasting."""
    import numpy as np
    import pandas as pd
    from pyproj import Geod
    from shapely.geometry import MultiPoint, mapping

    if direction not in (-1, 1) or duration_hours <= 0 or step_minutes <= 0:
        raise HTTPException(status_code=422, detail="Invalid drift direction, duration or step.")
    start_time = pd.Timestamp(observed_at)
    start_time = start_time.tz_localize("UTC") if start_time.tzinfo is None else start_time.tz_convert("UTC")
    field = EnvironmentalField(observations)
    geod = Geod(ellps="WGS84")
    rng = np.random.default_rng(random_seed)
    north = rng.normal(0, initial_spread_meters, particle_count)
    east = rng.normal(0, initial_spread_meters, particle_count)
    longitudes, latitudes, _ = geod.fwd(np.full(particle_count,longitude), np.full(particle_count,latitude), np.degrees(np.arctan2(east,north)), np.hypot(east,north))

    def move(lats, lons, velocities, dt):
        east = (velocities[:,0]+windage_factor*velocities[:,2])*dt
        north = (velocities[:,1]+windage_factor*velocities[:,3])*dt
        lon, lat, _ = geod.fwd(lons,lats,np.degrees(np.arctan2(east,north)),np.hypot(east,north))
        return lat, lon

    elapsed = 0.0
    duration = duration_hours*3600
    trajectory_features = []
    while True:
        timestamp = start_time + timedelta(seconds=elapsed*direction)
        velocity = field.velocity(timestamp,latitudes,longitudes)
        mean = velocity.mean(axis=0)
        mean_longitude = float(np.degrees(np.arctan2(np.sin(np.radians(longitudes)).mean(),np.cos(np.radians(longitudes)).mean())))
        trajectory_features.append({"type":"Feature", "geometry":{"type":"Point","coordinates":[mean_longitude,float(latitudes.mean())]}, "properties":{"timestamp":timestamp.isoformat(), "current_u_mps":float(mean[0]), "current_v_mps":float(mean[1]), "wind_u_mps":float(mean[2]), "wind_v_mps":float(mean[3])}})
        if elapsed >= duration:
            break
        seconds = min(step_minutes*60, duration-elapsed)
        mid_lat, mid_lon = move(latitudes,longitudes,velocity,seconds*direction/2)
        middle = field.velocity(timestamp+timedelta(seconds=seconds*direction/2),mid_lat,mid_lon)
        latitudes,longitudes = move(latitudes,longitudes,middle,seconds*direction)
        elapsed += seconds
    if np.ptp(longitudes)>180:
        raise HTTPException(status_code=422, detail="The final particle envelope crosses the dateline. Split this case before displaying its regional envelope.")
    hull = MultiPoint(list(zip(longitudes,latitudes))).convex_hull
    if hull.geom_type in ("Point","LineString"):
        hull = hull.buffer(0.00001)
    return {
        "trajectory":{"type":"FeatureCollection","features":trajectory_features},
        "probability_region":{"type":"Feature","geometry":mapping(hull),"properties":{"particle_count":particle_count,"interpretation":"Convex envelope of final particle locations, not a calibrated probability contour. Degenerate envelopes have a small display buffer."}},
        "sampling":{"method":"per-particle four-neighbor inverse-distance spatial interpolation and linear temporal interpolation", "integrator":"midpoint RK2 on WGS84", "maximum_time_gap_minutes":round(field.maximum_time_gap_minutes,3), "maximum_nearest_observation_distance_km":round(field.maximum_distance_km,3), "maximum_allowed_distance_km":100, "maximum_allowed_time_gap_minutes":360, "step_minutes":step_minutes, "windage_factor":windage_factor, "warnings":sorted(field.warnings), "limitations":"No tides, Stokes drift, diffusion, weathering or coastline collision. Reverse advection does not establish release age."},
    }
