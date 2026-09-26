import { useEffect, useMemo, useRef, useState } from "react";
import {
  CircleMarker, GeoJSON as GeoJSONLayer, ImageOverlay, LayerGroup, LayersControl, MapContainer,
  Marker, Polyline, Popup, Rectangle, ScaleControl, TileLayer, Tooltip, useMap,
} from "react-leaflet";
import type { LatLngBoundsExpression, LatLngTuple, Layer, PathOptions } from "leaflet";
import * as L from "leaflet";
import "leaflet/dist/leaflet.css";

import type { CandidateVessel, DriftResponse, VesselTrackPosition } from "../types/api";
import { bboxToLatLngBounds, computeBBox, computeCentroid, scoreToColor, toLatLngPath } from "../lib/geo";

const DEFAULT_CENTER: LatLngTuple = [15.5, 71.5];
const DEFAULT_ZOOM = 6;

export interface SatelliteAssetView {
  geojson: GeoJSON.FeatureCollection;
  bounds: [number, number, number, number] | null;
  imageUrl: string | null;
  groundTruthUrl: string | null;
  centroid?: LatLngTuple | null;
}

interface MaritimeMapProps {
  satellite: SatelliteAssetView | null;
  backwardDrift: DriftResponse | null;
  forwardDrift: DriftResponse | null;
  candidates: CandidateVessel[];
  selectedMmsi: string | null;
  onSelectVessel: (mmsi: string) => void;
}

function trajectoryToPositions(trajectory: GeoJSON.FeatureCollection): LatLngTuple[] {
  return trajectory.features
    .map((feature) => (feature.geometry.type === "Point" ? feature.geometry.coordinates : null))
    .filter((coordinates): coordinates is GeoJSON.Position => coordinates !== null)
    .map(([lng, lat]) => [lat, lng] as LatLngTuple);
}

function FitToEvidence({ bounds }: { bounds: LatLngBoundsExpression | null }) {
  const map = useMap();
  const signature = useMemo(() => JSON.stringify(bounds), [bounds]);
  useEffect(() => {
    if (bounds) map.fitBounds(bounds, { padding: [48, 48], maxZoom: 13 });
    // signature is a stable dependency for Leaflet bounds arrays.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature, map]);
  return null;
}

function FlyToSelection({ target }: { target: { bounds: LatLngBoundsExpression; center: LatLngTuple } | null }) {
  const map = useMap();
  useEffect(() => {
    if (!target) return;
    try { map.flyToBounds(target.bounds, { padding: [64, 64], maxZoom: 12, duration: 0.9 }); }
    catch { map.flyTo(target.center, 11, { duration: 0.9 }); }
  }, [target, map]);
  return null;
}

function AnimatedTracer({ path, kind }: { path: LatLngTuple[]; kind: "backward" | "forward" }) {
  const map = useMap();
  useEffect(() => {
    if (!path.length) return;
    const icon = L.divIcon({ className: `particle-tracer particle-tracer--${kind}`, html: "<span></span>", iconSize: [16, 16], iconAnchor: [8, 8] });
    const marker = L.marker(path[0], { icon, interactive: false }).addTo(map);
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || path.length === 1) {
      marker.setLatLng(path[path.length - 1]);
      return () => marker.remove();
    }
    let frame = 0;
    const startedAt = performance.now();
    const duration = Math.max(5000, path.length * 180);
    const animate = (now: number) => {
      const scaled = (((now - startedAt) % duration) / duration) * (path.length - 1);
      const index = Math.min(path.length - 2, Math.floor(scaled));
      const fraction = scaled - index;
      marker.setLatLng([
        path[index][0] + (path[index + 1][0] - path[index][0]) * fraction,
        path[index][1] + (path[index + 1][1] - path[index][1]) * fraction,
      ]);
      frame = requestAnimationFrame(animate);
    };
    frame = requestAnimationFrame(animate);
    return () => { cancelAnimationFrame(frame); marker.remove(); };
  }, [map, path, kind]);
  return null;
}

function vectorMarkers(drift: DriftResponse | null) {
  if (!drift) return [];
  const stride = Math.max(1, Math.ceil(drift.trajectory.features.length / 10));
  return drift.trajectory.features.flatMap((feature, index) => {
    if (index % stride !== 0 || feature.geometry.type !== "Point") return [];
    const properties = feature.properties ?? {};
    const currentU = Number(properties.current_u_mps ?? 0);
    const currentV = Number(properties.current_v_mps ?? 0);
    const windU = Number(properties.wind_u_mps ?? 0);
    const windV = Number(properties.wind_v_mps ?? 0);
    return [{
      position: [feature.geometry.coordinates[1], feature.geometry.coordinates[0]] as LatLngTuple,
      timestamp: String(properties.timestamp ?? ""),
      current: { speed: Math.hypot(currentU, currentV), heading: (Math.atan2(currentU, currentV) * 180) / Math.PI },
      wind: { speed: Math.hypot(windU, windV), heading: (Math.atan2(windU, windV) * 180) / Math.PI },
    }];
  });
}

function arrowIcon(kind: "current" | "wind" | "vessel", heading: number): L.DivIcon {
  return L.divIcon({ className: `map-vector map-vector--${kind}`, html: `<span style="transform:rotate(${heading.toFixed(1)}deg)">➤</span>`, iconSize: [22, 22], iconAnchor: [11, 11] });
}

function trackPositions(candidate: CandidateVessel): VesselTrackPosition[] {
  const raw = candidate.track_geojson.properties?.positions;
  return Array.isArray(raw) ? (raw as unknown as VesselTrackPosition[]) : [];
}

function spillPathOptions(opacity: number): PathOptions {
  return { color: "#ff5470", weight: 2, fillColor: "#ff5470", fillOpacity: opacity };
}

function probabilityStyle(feature: GeoJSON.Feature | undefined, opacity: number): PathOptions {
  const probability = Number(feature?.properties?.mean_model_probability ?? 0);
  const hue = 210 - Math.max(0, Math.min(1, probability)) * 210;
  return { color: `hsl(${hue}, 90%, 62%)`, weight: 1, fillColor: `hsl(${hue}, 90%, 52%)`, fillOpacity: opacity * 0.72 };
}

function envelopePathOptions(kind: "backward" | "forward"): PathOptions {
  return kind === "backward"
    ? { color: "#f4c969", weight: 1.5, dashArray: "6 4", fillColor: "#f4c969", fillOpacity: 0.08 }
    : { color: "#7fd1ff", weight: 1.5, dashArray: "2 4", fillColor: "#7fd1ff", fillOpacity: 0.08 };
}

export function MaritimeMap({ satellite, backwardDrift, forwardDrift, candidates, selectedMmsi, onSelectVessel }: MaritimeMapProps) {
  const [maskOpacity, setMaskOpacity] = useState(0.38);
  const mapRef = useRef<L.Map | null>(null);
  const spillCentroid = useMemo(() => (satellite ? satellite.centroid ?? computeCentroid(satellite.geojson) : null), [satellite]);
  const backwardPath = useMemo(() => (backwardDrift ? trajectoryToPositions(backwardDrift.trajectory) : []), [backwardDrift]);
  const forwardPath = useMemo(() => (forwardDrift ? trajectoryToPositions(forwardDrift.trajectory) : []), [forwardDrift]);
  const vectors = useMemo(() => vectorMarkers(backwardDrift ?? forwardDrift), [backwardDrift, forwardDrift]);

  const combinedBounds = useMemo<LatLngBoundsExpression | null>(() => {
    const boxes: [number, number, number, number][] = [];
    if (satellite) { const box = satellite.bounds ?? computeBBox(satellite.geojson); if (box) boxes.push(box); }
    [backwardDrift?.probability_region, forwardDrift?.probability_region].forEach((region) => { const box = computeBBox(region); if (box) boxes.push(box); });
    candidates.forEach((candidate) => { const box = computeBBox(candidate.track_geojson); if (box) boxes.push(box); });
    if (!boxes.length) return null;
    return bboxToLatLngBounds([Math.min(...boxes.map((box) => box[0])), Math.min(...boxes.map((box) => box[1])), Math.max(...boxes.map((box) => box[2])), Math.max(...boxes.map((box) => box[3]))]);
  }, [satellite, backwardDrift, forwardDrift, candidates]);

  const selectionTarget = useMemo(() => {
    const candidate = candidates.find((item) => item.mmsi === selectedMmsi);
    const box = candidate ? computeBBox(candidate.track_geojson) : null;
    const centroid = candidate ? computeCentroid(candidate.track_geojson) : null;
    return box && centroid ? { bounds: bboxToLatLngBounds(box), center: centroid as LatLngTuple } : null;
  }, [selectedMmsi, candidates]);
  const rasterBounds = satellite?.bounds ? bboxToLatLngBounds(satellite.bounds) : null;

  return (
    <section className="map-stage" aria-label="Integrated forensic map">
      <div className="map-stage__toolbar">
        <div><strong>Forensic evidence map</strong><span>SAR → drift → vessel attribution</span></div>
        <label><span>Mask opacity <b>{Math.round(maskOpacity * 100)}%</b></span><input type="range" min="0" max="0.9" step="0.05" value={maskOpacity} onChange={(event) => setMaskOpacity(Number(event.target.value))} /></label>
      </div>
      <div className="maritime-map">
        <div className="map-context-controls">
          <button type="button" onClick={() => mapRef.current?.setView(DEFAULT_CENTER, DEFAULT_ZOOM)}>Regional context</button>
          <button type="button" disabled={!combinedBounds} onClick={() => combinedBounds && mapRef.current?.fitBounds(combinedBounds, { padding: [48, 48], maxZoom: 13 })}>Fit evidence</button>
        </div>
        <MapContainer ref={mapRef} center={spillCentroid ?? DEFAULT_CENTER} zoom={DEFAULT_ZOOM} worldCopyJump>
          <LayersControl position="topright">
            <LayersControl.BaseLayer checked name="Labeled street and coastline map"><TileLayer attribution='&copy; OpenStreetMap contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" /></LayersControl.BaseLayer>
            <LayersControl.BaseLayer name="Satellite imagery basemap"><TileLayer attribution="Tiles &copy; Esri" url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}" /></LayersControl.BaseLayer>
            <LayersControl.Overlay name="Shipping lanes + marine marks"><TileLayer attribution="Map data &copy; OpenSeaMap contributors" url="https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png" opacity={0.72} /></LayersControl.Overlay>

            {satellite?.imageUrl && rasterBounds && <LayersControl.Overlay checked name="Original SAR image"><ImageOverlay url={satellite.imageUrl} bounds={rasterBounds} opacity={0.78} /></LayersControl.Overlay>}
            {satellite?.groundTruthUrl && rasterBounds && <LayersControl.Overlay name="Ground truth (validation only)"><ImageOverlay url={satellite.groundTruthUrl} bounds={rasterBounds} opacity={maskOpacity} className="ground-truth-overlay" /></LayersControl.Overlay>}
            {rasterBounds && <LayersControl.Overlay checked name="SAR acquisition footprint"><Rectangle bounds={rasterBounds} pathOptions={{ color: "#3bbccc", weight: 1, dashArray: "4 4", fillOpacity: 0.01 }} /></LayersControl.Overlay>}
            {satellite && satellite.geojson.features.length > 0 && <>
              <LayersControl.Overlay name="Segmentation probability heatmap"><GeoJSONLayer key={`heat-${maskOpacity}`} data={satellite.geojson} style={(feature) => probabilityStyle(feature, maskOpacity)} /></LayersControl.Overlay>
              <LayersControl.Overlay checked name="Detected spill mask + centroid"><LayerGroup>
                <GeoJSONLayer key={`spill-${maskOpacity}`} data={satellite.geojson} style={() => spillPathOptions(maskOpacity)} onEachFeature={(feature: GeoJSON.Feature, layer: Layer) => { const properties = feature.properties ?? {}; layer.bindPopup(`<strong>Detected spill segment</strong><br/>Mean probability: ${Number(properties.mean_model_probability ?? 0).toFixed(3)}<br/>Max probability: ${Number(properties.max_model_probability ?? 0).toFixed(3)}<br/>Pixels: ${properties.pixel_count ?? "—"}`); }} />
                {spillCentroid && <CircleMarker center={spillCentroid} radius={6} pathOptions={{ color: "#ff5470", fillColor: "#fff", fillOpacity: 1, weight: 2 }}><Tooltip permanent direction="top" offset={[0, -8]} className="map-tooltip">Spill centroid</Tooltip></CircleMarker>}
              </LayerGroup></LayersControl.Overlay>
            </>}

            {backwardDrift && <LayersControl.Overlay checked name="Backward hindcast"><LayerGroup><Polyline positions={backwardPath} pathOptions={{ color: "#f4c969", weight: 3, dashArray: "6 4" }} /><GeoJSONLayer data={backwardDrift.probability_region} style={() => envelopePathOptions("backward")} /><AnimatedTracer path={backwardPath} kind="backward" /></LayerGroup></LayersControl.Overlay>}
            {forwardDrift && <LayersControl.Overlay checked name="Forward forecast"><LayerGroup><Polyline positions={forwardPath} pathOptions={{ color: "#7fd1ff", weight: 3 }} /><GeoJSONLayer data={forwardDrift.probability_region} style={() => envelopePathOptions("forward")} /><AnimatedTracer path={forwardPath} kind="forward" /></LayerGroup></LayersControl.Overlay>}
            {vectors.length > 0 && <LayersControl.Overlay checked name="Wind + current vectors"><LayerGroup>{vectors.flatMap((vector, index) => [
              <Marker key={`current-${index}`} position={vector.position} icon={arrowIcon("current", vector.current.heading)}><Popup>Current {vector.current.speed.toFixed(2)} m/s<br />{vector.timestamp}</Popup></Marker>,
              <Marker key={`wind-${index}`} position={vector.position} icon={arrowIcon("wind", vector.wind.heading)}><Popup>Wind {vector.wind.speed.toFixed(2)} m/s<br />{vector.timestamp}</Popup></Marker>,
            ])}</LayerGroup></LayersControl.Overlay>}
            {candidates.length > 0 && <LayersControl.Overlay checked name="AIS vessel tracks + timestamped positions"><LayerGroup>{candidates.map((candidate) => {
              const path = toLatLngPath(candidate.track_geojson.geometry);
              const positions = trackPositions(candidate);
              const stride = Math.max(1, Math.ceil(positions.length / 12));
              const color = scoreToColor(candidate.evidence_score * 100);
              const selected = candidate.mmsi === selectedMmsi;
              return <LayerGroup key={candidate.mmsi}>
                {path.length > 1 && <Polyline positions={path} pathOptions={{ color, weight: selected ? 5 : 2.5, opacity: selected ? 1 : 0.72 }} eventHandlers={{ click: () => onSelectVessel(candidate.mmsi) }} />}
                {positions.filter((_, index) => index % stride === 0).map((position, index) => <Marker key={`${candidate.mmsi}-${index}`} position={[position.latitude, position.longitude]} icon={arrowIcon("vessel", position.course_degrees ?? 0)} eventHandlers={{ click: () => onSelectVessel(candidate.mmsi) }}><Popup><strong>MMSI {candidate.mmsi}</strong><br />{new Date(position.timestamp).toLocaleString()}<br />Course {position.course_degrees?.toFixed(0) ?? "—"}° · {position.speed_knots?.toFixed(1) ?? "—"} kn<br />{position.distance_to_origin_km.toFixed(2)} km from origin</Popup></Marker>)}
                {path.length > 0 && <CircleMarker center={path[path.length - 1]} radius={selected ? 8 : 5} pathOptions={{ color, fillColor: color, fillOpacity: .9, weight: selected ? 3 : 1.5 }} eventHandlers={{ click: () => onSelectVessel(candidate.mmsi) }} />}
              </LayerGroup>;
            })}</LayerGroup></LayersControl.Overlay>}
          </LayersControl>
          <ScaleControl position="bottomleft" imperial={false} />
          <FitToEvidence bounds={combinedBounds} /><FlyToSelection target={selectionTarget} />
        </MapContainer>
        <div className="map-legend" aria-label="Map legend"><span><i className="legend-dot legend-dot--spill" />Spill</span><span><i className="legend-line legend-line--backward" />Hindcast</span><span><i className="legend-line legend-line--forward" />Forecast</span><span><i className="legend-arrow legend-arrow--current">➤</i>Current</span><span><i className="legend-arrow legend-arrow--wind">➤</i>Wind</span></div>
      </div>
    </section>
  );
}
