import { useEffect, useMemo, useRef } from "react";
import {
  CircleMarker,
  GeoJSON as GeoJSONLayer,
  LayerGroup,
  LayersControl,
  MapContainer,
  Polyline,
  Popup,
  Rectangle,
  TileLayer,
  Tooltip,
  useMap,
} from "react-leaflet";
import type { LatLngBoundsExpression, LatLngTuple, Layer, PathOptions } from "leaflet";
import * as L from "leaflet";
import "leaflet/dist/leaflet.css";

import type { CandidateVessel, DriftResponse } from "../types/api";
import { bboxToLatLngBounds, computeBBox, computeCentroid, scoreToColor, toLatLngPath } from "../lib/geo";

const DEFAULT_CENTER: LatLngTuple = [15.5, 71.5]; // Eastern Arabian Sea — a reasonable idle view
const DEFAULT_ZOOM = 6;

export interface SatelliteAssetView {
  geojson: GeoJSON.FeatureCollection;
  bounds: [number, number, number, number] | null; // [west, south, east, north]
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

/** Fits the viewport to every layer currently on the map whenever the underlying evidence changes. */
function FitToEvidence({ bounds }: { bounds: LatLngBoundsExpression | null }) {
  const map = useMap();
  const signature = useMemo(() => JSON.stringify(bounds), [bounds]);

  useEffect(() => {
    if (!bounds) return;
    map.fitBounds(bounds, { padding: [48, 48], maxZoom: 13 });
    // `signature` intentionally drives this effect instead of the `bounds` array reference.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature, map]);

  return null;
}

/** Pans/zooms to a candidate vessel's track whenever the panel selection changes. */
function FlyToSelection({ target }: { target: { bounds: LatLngBoundsExpression; center: LatLngTuple } | null }) {
  const map = useMap();

  useEffect(() => {
    if (!target) return;
    try {
      map.flyToBounds(target.bounds, { padding: [64, 64], maxZoom: 12, duration: 0.9 });
    } catch {
      map.flyTo(target.center, 11, { duration: 0.9 });
    }
  }, [target, map]);

  return null;
}

function spillPathOptions(): PathOptions {
  return { color: "#ff5470", weight: 2, fillColor: "#ff5470", fillOpacity: 0.28 };
}

function envelopePathOptions(kind: "backward" | "forward"): PathOptions {
  return kind === "backward"
    ? { color: "#f4c969", weight: 1.5, dashArray: "6 4", fillColor: "#f4c969", fillOpacity: 0.08 }
    : { color: "#7fd1ff", weight: 1.5, dashArray: "2 4", fillColor: "#7fd1ff", fillOpacity: 0.08 };
}

export function MaritimeMap({ satellite, backwardDrift, forwardDrift, candidates, selectedMmsi, onSelectVessel }: MaritimeMapProps) {
  const mapRef = useRef<L.Map | null>(null);

  const spillCentroid = useMemo(() => (satellite ? computeCentroid(satellite.geojson) : null), [satellite]);

  const combinedBounds = useMemo<LatLngBoundsExpression | null>(() => {
    const boxes: [number, number, number, number][] = [];
    if (satellite) {
      const box = satellite.bounds ?? computeBBox(satellite.geojson);
      if (box) boxes.push(box);
    }
    if (backwardDrift) {
      const box = computeBBox(backwardDrift.probability_region);
      if (box) boxes.push(box);
    }
    if (forwardDrift) {
      const box = computeBBox(forwardDrift.probability_region);
      if (box) boxes.push(box);
    }
    candidates.forEach((candidate) => {
      const box = computeBBox(candidate.track_geojson);
      if (box) boxes.push(box);
    });
    if (boxes.length === 0) return null;
    const west = Math.min(...boxes.map((box) => box[0]));
    const south = Math.min(...boxes.map((box) => box[1]));
    const east = Math.max(...boxes.map((box) => box[2]));
    const north = Math.max(...boxes.map((box) => box[3]));
    return bboxToLatLngBounds([west, south, east, north]);
  }, [satellite, backwardDrift, forwardDrift, candidates]);

  const selectionTarget = useMemo(() => {
    if (!selectedMmsi) return null;
    const candidate = candidates.find((item) => item.mmsi === selectedMmsi);
    if (!candidate) return null;
    const box = computeBBox(candidate.track_geojson);
    const centroid = computeCentroid(candidate.track_geojson);
    if (!box || !centroid) return null;
    return { bounds: bboxToLatLngBounds(box), center: centroid as LatLngTuple };
  }, [selectedMmsi, candidates]);

  const satelliteRectangle = useMemo<LatLngBoundsExpression | null>(() => {
    const box = satellite?.bounds ?? (satellite ? computeBBox(satellite.geojson) : null);
    return box ? bboxToLatLngBounds(box) : null;
  }, [satellite]);

  return (
    <div className="maritime-map">
      <MapContainer
        center={spillCentroid ?? DEFAULT_CENTER}
        zoom={DEFAULT_ZOOM}
        worldCopyJump
        ref={(instance) => {
          mapRef.current = instance;
        }}
      >
        <LayersControl position="topright">
          <LayersControl.BaseLayer checked name="Dark ocean basemap">
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
              url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
            />
          </LayersControl.BaseLayer>
          <LayersControl.BaseLayer name="Satellite imagery basemap">
            <TileLayer
              attribution="Tiles &copy; Esri — Source: Esri, Maxar, Earthstar Geographics"
              url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
            />
          </LayersControl.BaseLayer>

          {satelliteRectangle && (
            <LayersControl.Overlay checked name="Satellite raster preview bounds">
              <Rectangle bounds={satelliteRectangle} pathOptions={{ color: "#3bbccc", weight: 1, dashArray: "4 4", fillOpacity: 0.02 }} />
            </LayersControl.Overlay>
          )}

          {satellite && satellite.geojson.features.length > 0 && (
            <LayersControl.Overlay checked name="Detected oil-spill polygon + centroid">
              <LayerGroup>
                <GeoJSONLayer
                  key={`spill-${satellite.geojson.features.length}`}
                  data={satellite.geojson}
                  style={spillPathOptions}
                  onEachFeature={(feature: GeoJSON.Feature, layer: Layer) => {
                    const properties = feature.properties ?? {};
                    layer.bindPopup(
                      `<strong>Detected spill segment</strong><br/>Mean model probability: ${Number(properties.mean_model_probability ?? 0).toFixed(3)}<br/>Pixels: ${properties.pixel_count ?? "—"}`,
                    );
                  }}
                />
                {spillCentroid && (
                  <CircleMarker center={spillCentroid} radius={6} pathOptions={{ color: "#ff5470", fillColor: "#ffffff", fillOpacity: 1, weight: 2 }}>
                    <Tooltip permanent direction="top" offset={[0, -8]} className="map-tooltip">
                      Spill centroid
                    </Tooltip>
                  </CircleMarker>
                )}
              </LayerGroup>
            </LayersControl.Overlay>
          )}

          {backwardDrift && (
            <LayersControl.Overlay checked name="Backward drift hindcast + origin probability envelope">
              <LayerGroup>
                <Polyline positions={trajectoryToPositions(backwardDrift.trajectory)} pathOptions={{ color: "#f4c969", weight: 2.5, dashArray: "6 4" }} />
                <GeoJSONLayer key="backward-envelope" data={backwardDrift.probability_region} style={() => envelopePathOptions("backward")} />
              </LayerGroup>
            </LayersControl.Overlay>
          )}

          {forwardDrift && (
            <LayersControl.Overlay checked name="Forward drift prediction">
              <LayerGroup>
                <Polyline positions={trajectoryToPositions(forwardDrift.trajectory)} pathOptions={{ color: "#7fd1ff", weight: 2.5 }} />
                <GeoJSONLayer key="forward-envelope" data={forwardDrift.probability_region} style={() => envelopePathOptions("forward")} />
              </LayerGroup>
            </LayersControl.Overlay>
          )}

          {candidates.length > 0 && (
            <LayersControl.Overlay checked name="AIS vessel tracks (suspect ranking)">
              <LayerGroup>
                {candidates.map((candidate) => {
                  const path = toLatLngPath(candidate.track_geojson.geometry);
                  const color = scoreToColor(candidate.evidence_score * 100);
                  const isSelected = candidate.mmsi === selectedMmsi;
                  return (
                    <LayerGroup key={candidate.mmsi}>
                      {path.length > 1 && (
                        <Polyline
                          positions={path}
                          pathOptions={{ color, weight: isSelected ? 5 : 2.5, opacity: isSelected ? 1 : 0.75 }}
                          eventHandlers={{ click: () => onSelectVessel(candidate.mmsi) }}
                        >
                          <Popup>
                            <strong>MMSI {candidate.mmsi}</strong>
                            <br />
                            {candidate.vessel_type ?? "Unknown vessel type"}
                            <br />
                            Score: {(candidate.evidence_score * 100).toFixed(1)} / 100
                          </Popup>
                        </Polyline>
                      )}
                      {path.length > 0 && (
                        <CircleMarker
                          center={path[path.length - 1]}
                          radius={isSelected ? 8 : 5}
                          pathOptions={{ color, fillColor: color, fillOpacity: 0.9, weight: isSelected ? 3 : 1.5 }}
                          eventHandlers={{ click: () => onSelectVessel(candidate.mmsi) }}
                        >
                          <Popup>
                            <strong>MMSI {candidate.mmsi}</strong>
                            <br />
                            Latest tracked position in evidence window
                          </Popup>
                        </CircleMarker>
                      )}
                    </LayerGroup>
                  );
                })}
              </LayerGroup>
            </LayersControl.Overlay>
          )}
        </LayersControl>

        <FitToEvidence bounds={combinedBounds} />
        <FlyToSelection target={selectionTarget} />
      </MapContainer>
    </div>
  );
}
