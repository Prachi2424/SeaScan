"""Regional WGS84 slick measurements; centroid/orientation use local equal-area projection."""
import math
import numpy as np
from pyproj import CRS, Geod, Transformer
from shapely.geometry import shape
from shapely.geometry.polygon import orient
from shapely.ops import transform, unary_union


def calculate_spill_metrics(geojson):
    empty = dict(component_count=0, area_km2=None, perimeter_km=None, centroid=None, bounds=None, orientation_degrees=None)
    if not geojson or not geojson.get("features"):
        return empty
    polygons = []
    for feature in geojson["features"]:
        geometry = shape(feature["geometry"])
        if geometry.geom_type not in ("Polygon", "MultiPolygon") or geometry.is_empty:
            continue
        if not geometry.is_valid:
            raise ValueError("Spill geometry must be valid Polygon or MultiPolygon data.")
        polygons.extend([geometry] if geometry.geom_type == "Polygon" else geometry.geoms)
    if not polygons:
        return empty
    coords = np.array([point[:2] for polygon in polygons for point in polygon.exterior.coords])
    if not np.isfinite(coords).all() or (abs(coords[:,1])>90).any():
        raise ValueError("Spill coordinates must be finite WGS84 longitude/latitude.")
    lon = math.degrees(math.atan2(np.sin(np.radians(coords[:,0])).mean(),np.cos(np.radians(coords[:,0])).mean()))
    lat = float(coords[:,1].mean())
    def unwrap(x,y,z=None):
        return lon + (np.asarray(x)-lon+180)%360-180, y
    unwrapped = [transform(unwrap,p) for p in polygons]
    extent = unary_union(unwrapped).bounds
    if extent[2]-extent[0]>20 or extent[3]-extent[1]>20:
        raise ValueError("Spill geometry spans more than 20 degrees; divide it into regional cases.")
    local = CRS.from_proj4(f"+proj=laea +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m")
    forward = Transformer.from_crs("EPSG:4326",local,always_xy=True)
    backward = Transformer.from_crs(local,"EPSG:4326",always_xy=True)
    merged = unary_union([transform(forward.transform,p) for p in unwrapped])
    geographic = transform(backward.transform,merged)
    components = [geographic] if geographic.geom_type=="Polygon" else list(geographic.geoms)
    geod = Geod(ellps="WGS84")
    area = perimeter = 0.0
    for polygon in components:
        signed_area,_ = geod.geometry_area_perimeter(orient(polygon,sign=1.0))
        area += abs(signed_area)
        for ring in [polygon.exterior,*polygon.interiors]:
            perimeter += geod.geometry_length(ring)
    centroid = backward.transform(merged.centroid.x,merged.centroid.y)
    rectangle = merged.minimum_rotated_rectangle
    bearing = None
    if rectangle.geom_type=="Polygon":
        points=list(rectangle.exterior.coords)
        edges=[(math.hypot(b[0]-a[0],b[1]-a[1]),b[0]-a[0],b[1]-a[1]) for a,b in zip(points,points[1:])]
        longest=max(edges)
        if min(e[0] for e in edges)>0 and longest[0]/min(e[0] for e in edges)>1.05:
            bearing=round(math.degrees(math.atan2(longest[1],longest[2]))%180,3)
    return dict(component_count=len(components),area_km2=round(area/1e6,6),perimeter_km=round(perimeter/1000,6),centroid=[round(v,7) for v in centroid],bounds=list(extent),orientation_degrees=bearing,measurement_method="WGS84 ellipsoidal area/perimeter; local equal-area union centroid and major-axis orientation",orientation_note="Degrees clockwise from local projected north, modulo 180; undefined for near-square shapes. Bounds may extend past 180 degrees across the dateline.")
