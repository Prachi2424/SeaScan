/**
 * Small, dependency-free geometry helpers for GeoJSON produced by the SeaScan
 * backend. Nothing here fabricates data — every function only reshapes or
 * measures coordinates that were already returned by a real backend response.
 */

export type LngLat = [number, number];
export type LatLng = [number, number];

export interface GeometryMetrics {
  areaKm2: number;
  perimeterKm: number;
  orientationDegrees: number | null;
  centroid: LatLng | null;
}

function eachRing(geometry: GeoJSON.Geometry, visit: (ring: GeoJSON.Position[]) => void): void {
  switch (geometry.type) {
    case "Point":
      visit([geometry.coordinates]);
      return;
    case "MultiPoint":
    case "LineString":
      visit(geometry.coordinates);
      return;
    case "MultiLineString":
      geometry.coordinates.forEach((line) => visit(line));
      return;
    case "Polygon":
      geometry.coordinates.forEach((ring) => visit(ring));
      return;
    case "MultiPolygon":
      geometry.coordinates.forEach((polygon) => polygon.forEach((ring) => visit(ring)));
      return;
    case "GeometryCollection":
      geometry.geometries.forEach((child) => eachRing(child, visit));
      return;
    default:
      return;
  }
}

/** Bounding box of any GeoJSON geometry/feature/collection, as [west, south, east, north]. */
export function computeBBox(
  input: GeoJSON.FeatureCollection | GeoJSON.Feature | GeoJSON.Geometry | null | undefined,
): [number, number, number, number] | null {
  if (!input) return null;
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;

  const visitGeometry = (geometry: GeoJSON.Geometry | null) => {
    if (!geometry) return;
    eachRing(geometry, (ring) => {
      for (const [lng, lat] of ring) {
        if (lng < west) west = lng;
        if (lng > east) east = lng;
        if (lat < south) south = lat;
        if (lat > north) north = lat;
      }
    });
  };

  if (input.type === "FeatureCollection") {
    input.features.forEach((feature) => visitGeometry(feature.geometry));
  } else if (input.type === "Feature") {
    visitGeometry(input.geometry);
  } else {
    visitGeometry(input);
  }

  if (!Number.isFinite(west) || !Number.isFinite(south) || !Number.isFinite(east) || !Number.isFinite(north)) {
    return null;
  }
  return [west, south, east, north];
}

/** Converts a [west, south, east, north] bbox to Leaflet's [[south, west], [north, east]] literal. */
export function bboxToLatLngBounds(bbox: [number, number, number, number]): [LatLng, LatLng] {
  const [west, south, east, north] = bbox;
  return [
    [south, west],
    [north, east],
  ];
}

/** Signed area / centroid of a single linear ring using the shoelace formula (in [lng, lat] space). */
function ringCentroid(ring: GeoJSON.Position[]): { centroid: LngLat; area: number } | null {
  if (ring.length < 3) return null;
  let area = 0;
  let cx = 0;
  let cy = 0;
  for (let i = 0; i < ring.length - 1; i += 1) {
    const [x0, y0] = ring[i];
    const [x1, y1] = ring[i + 1];
    const cross = x0 * y1 - x1 * y0;
    area += cross;
    cx += (x0 + x1) * cross;
    cy += (y0 + y1) * cross;
  }
  area /= 2;
  if (area === 0) return null;
  return { centroid: [cx / (6 * area), cy / (6 * area)], area: Math.abs(area) };
}

/**
 * Area-weighted centroid for polygon geometries (the real formula, not a bounding-box
 * approximation). Falls back to a coordinate average for point/line geometries, and to
 * the largest polygon's centroid for a mixed FeatureCollection.
 */
export function computeCentroid(
  input: GeoJSON.FeatureCollection | GeoJSON.Feature | GeoJSON.Geometry | null | undefined,
): LatLng | null {
  if (!input) return null;

  const polygonRings: GeoJSON.Position[][] = [];
  const rawPoints: GeoJSON.Position[] = [];

  const collect = (geometry: GeoJSON.Geometry | null) => {
    if (!geometry) return;
    if (geometry.type === "Polygon") {
      polygonRings.push(geometry.coordinates[0]);
    } else if (geometry.type === "MultiPolygon") {
      geometry.coordinates.forEach((polygon) => polygonRings.push(polygon[0]));
    } else {
      eachRing(geometry, (ring) => rawPoints.push(...ring));
    }
  };

  if (input.type === "FeatureCollection") {
    input.features.forEach((feature) => collect(feature.geometry));
  } else if (input.type === "Feature") {
    collect(input.geometry);
  } else {
    collect(input);
  }

  if (polygonRings.length > 0) {
    let totalArea = 0;
    let sumLng = 0;
    let sumLat = 0;
    for (const ring of polygonRings) {
      const result = ringCentroid(ring);
      if (!result) continue;
      totalArea += result.area;
      sumLng += result.centroid[0] * result.area;
      sumLat += result.centroid[1] * result.area;
    }
    if (totalArea > 0) {
      return [sumLat / totalArea, sumLng / totalArea];
    }
  }

  if (rawPoints.length > 0) {
    const sum = rawPoints.reduce(
      (acc, [lng, lat]) => [acc[0] + lng, acc[1] + lat] as LngLat,
      [0, 0] as LngLat,
    );
    return [sum[1] / rawPoints.length, sum[0] / rawPoints.length];
  }

  return null;
}

/** Extracts [lat, lng] pairs from any geometry's coordinates, for feeding into Leaflet primitives. */
export function toLatLngPath(geometry: GeoJSON.Geometry | null | undefined): LatLng[] {
  if (!geometry) return [];
  const path: LatLng[] = [];
  eachRing(geometry, (ring) => {
    for (const [lng, lat] of ring) path.push([lat, lng]);
  });
  return path;
}

/** Maps a 0-100 evidence score to a red (high risk) → amber → green (low risk) hue. */
export function scoreToColor(score: number): string {
  const clamped = Math.max(0, Math.min(100, score));
  const hue = 120 - (clamped / 100) * 120; // 120 = green, 0 = red
  return `hsl(${hue.toFixed(0)}, 82%, 52%)`;
}

function haversineKm(a: GeoJSON.Position, b: GeoJSON.Position): number {
  const radius = 6371.0088;
  const [lng1, lat1] = a.map((value) => (value * Math.PI) / 180);
  const [lng2, lat2] = b.map((value) => (value * Math.PI) / 180);
  const dLat = lat2 - lat1;
  const dLng = lng2 - lng1;
  const value = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return radius * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value));
}

function polygonAreaKm2(ring: GeoJSON.Position[]): number {
  if (ring.length < 3) return 0;
  const meanLatitude = ring.reduce((sum, point) => sum + point[1], 0) / ring.length;
  const xScale = 111.32 * Math.cos((meanLatitude * Math.PI) / 180);
  const yScale = 110.574;
  let twiceArea = 0;
  for (let index = 0; index < ring.length - 1; index += 1) {
    const [lng1, lat1] = ring[index];
    const [lng2, lat2] = ring[index + 1];
    twiceArea += lng1 * xScale * lat2 * yScale - lng2 * xScale * lat1 * yScale;
  }
  return Math.abs(twiceArea) / 2;
}

/** Approximate geodesic spill metrics suitable for the dashboard summary. */
export function computeGeometryMetrics(input: GeoJSON.FeatureCollection | null | undefined): GeometryMetrics {
  const rings: GeoJSON.Position[][] = [];
  input?.features.forEach((feature) => {
    if (feature.geometry.type === "Polygon") rings.push(feature.geometry.coordinates[0]);
    if (feature.geometry.type === "MultiPolygon") feature.geometry.coordinates.forEach((polygon) => rings.push(polygon[0]));
  });
  let areaKm2 = 0;
  let perimeterKm = 0;
  const points: GeoJSON.Position[] = [];
  rings.forEach((ring) => {
    areaKm2 += polygonAreaKm2(ring);
    points.push(...ring);
    for (let index = 0; index < ring.length - 1; index += 1) perimeterKm += haversineKm(ring[index], ring[index + 1]);
  });
  const centroid = computeCentroid(input);
  let orientationDegrees: number | null = null;
  if (points.length >= 2 && centroid) {
    const [centerLat, centerLng] = centroid;
    const projected = points.map(([lng, lat]) => [
      (lng - centerLng) * Math.cos((centerLat * Math.PI) / 180),
      lat - centerLat,
    ]);
    const xx = projected.reduce((sum, [x]) => sum + x * x, 0) / projected.length;
    const yy = projected.reduce((sum, [, y]) => sum + y * y, 0) / projected.length;
    const xy = projected.reduce((sum, [x, y]) => sum + x * y, 0) / projected.length;
    orientationDegrees = ((0.5 * Math.atan2(2 * xy, xx - yy) * 180) / Math.PI + 360) % 180;
  }
  return { areaKm2, perimeterKm, orientationDegrees, centroid };
}
