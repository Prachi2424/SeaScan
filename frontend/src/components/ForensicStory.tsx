import { useMemo } from "react";
import { AreaChart, Compass, Crosshair, Route, Ruler, Timer } from "lucide-react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { computeGeometryMetrics, scoreToColor } from "../lib/geo";
import type {
  CandidateVessel, DriftResponse, EvidenceAsset, InvestigationSummary, SatelliteDetectionResponse, VesselTrackPosition,
} from "../types/api";

interface ForensicStoryProps {
  investigation: InvestigationSummary;
  satellite: SatelliteDetectionResponse | null;
  environmentAsset: EvidenceAsset | null;
  aisAsset: EvidenceAsset | null;
  backwardDrift: DriftResponse | null;
  forwardDrift: DriftResponse | null;
  candidates: CandidateVessel[];
}

function trackPositions(candidate: CandidateVessel): VesselTrackPosition[] {
  const raw = candidate.track_geojson.properties?.positions;
  return Array.isArray(raw) ? (raw as unknown as VesselTrackPosition[]) : [];
}

function formatCoordinate(value: number, positive: string, negative: string): string {
  return `${Math.abs(value).toFixed(5)}°${value >= 0 ? positive : negative}`;
}

function eventTime(value: string | undefined): number {
  const parsed = value ? new Date(value).getTime() : Number.NaN;
  return Number.isFinite(parsed) ? parsed : 0;
}

function MiniTrajectory({ drift, label, color }: { drift: DriftResponse | null; label: string; color: string }) {
  const points = drift?.trajectory.features.flatMap((feature) => feature.geometry.type === "Point" ? [[feature.geometry.coordinates[0], feature.geometry.coordinates[1]]] : []) ?? [];
  if (points.length < 2) return <div className="simulation-empty">Run the {label.toLowerCase()} to populate this view.</div>;
  const lngs = points.map(([lng]) => lng);
  const lats = points.map(([, lat]) => lat);
  const west = Math.min(...lngs); const east = Math.max(...lngs); const south = Math.min(...lats); const north = Math.max(...lats);
  const width = 360; const height = 170; const padding = 22;
  const x = (lng: number) => padding + ((lng - west) / Math.max(east - west, 1e-9)) * (width - padding * 2);
  const y = (lat: number) => height - padding - ((lat - south) / Math.max(north - south, 1e-9)) * (height - padding * 2);
  const path = points.map(([lng, lat], index) => `${index ? "L" : "M"}${x(lng).toFixed(2)},${y(lat).toFixed(2)}`).join(" ");
  return <svg className="simulation-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${label} trajectory with ${points.length} time steps`}>
    <defs><pattern id={`grid-${drift?.direction}`} width="24" height="24" patternUnits="userSpaceOnUse"><path d="M 24 0 L 0 0 0 24" fill="none" stroke="rgba(140,200,220,.08)" strokeWidth="1" /></pattern></defs>
    <rect width={width} height={height} fill={`url(#grid-${drift?.direction})`} />
    <path d={path} fill="none" stroke={color} strokeWidth="3" strokeDasharray={drift?.direction === "backward" ? "7 5" : undefined} />
    <circle cx={x(points[0][0])} cy={y(points[0][1])} r="5" fill="#ff5470" /><circle cx={x(points.at(-1)![0])} cy={y(points.at(-1)![1])} r="5" fill={color} />
    <text x={x(points[0][0]) + 8} y={y(points[0][1]) - 7}>Observed spill</text><text x={x(points.at(-1)![0]) + 8} y={y(points.at(-1)![1]) - 7}>{drift?.direction === "backward" ? "Estimated origin" : "Forecast extent"}</text>
  </svg>;
}

export function ForensicStory({ investigation, satellite, environmentAsset, aisAsset, backwardDrift, forwardDrift, candidates }: ForensicStoryProps) {
  const metrics = useMemo(() => computeGeometryMetrics(satellite?.geojson), [satellite]);
  const meanProbability = useMemo(() => {
    const values = satellite?.geojson.features.map((feature) => Number(feature.properties?.mean_model_probability ?? 0)) ?? [];
    return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
  }, [satellite]);
  const timeline = useMemo(() => [
    { time: investigation.created_at, title: "Investigation opened", detail: investigation.title, complete: true },
    { time: satellite?.asset.created_at, title: "SAR acquisition analysed", detail: satellite ? `${satellite.geojson.features.length} spill segment(s)` : "Awaiting satellite evidence", complete: Boolean(satellite) },
    { time: environmentAsset?.created_at, title: "Environmental field attached", detail: environmentAsset?.original_filename ?? "Awaiting wind/current evidence", complete: Boolean(environmentAsset) },
    { time: String(backwardDrift?.seed.observed_at ?? ""), title: "Origin hindcast", detail: backwardDrift ? `${backwardDrift.seed.duration_hours} h backward simulation` : "Not yet simulated", complete: Boolean(backwardDrift) },
    { time: String(forwardDrift?.seed.observed_at ?? ""), title: "Forward forecast", detail: forwardDrift ? `${forwardDrift.seed.duration_hours} h forward simulation` : "Not yet simulated", complete: Boolean(forwardDrift) },
    { time: aisAsset?.created_at, title: "AIS traffic correlated", detail: candidates.length ? `${candidates.length} candidate vessel(s) ranked` : "Awaiting attribution", complete: candidates.length > 0 },
  ].sort((a, b) => (a.complete === b.complete ? eventTime(a.time) - eventTime(b.time) : a.complete ? -1 : 1)), [investigation, satellite, environmentAsset, backwardDrift, forwardDrift, aisAsset, candidates]);

  return <div className="forensic-story">
    <section className="metrics-strip" aria-label="Spill geometry metrics">
      <article><AreaChart size={17} /><span>Spill area</span><strong>{satellite ? `${metrics.areaKm2.toFixed(2)} km²` : "—"}</strong></article>
      <article><Ruler size={17} /><span>Perimeter</span><strong>{satellite ? `${metrics.perimeterKm.toFixed(2)} km` : "—"}</strong></article>
      <article><Compass size={17} /><span>Orientation</span><strong>{metrics.orientationDegrees === null ? "—" : `${metrics.orientationDegrees.toFixed(1)}°`}</strong></article>
      <article><Crosshair size={17} /><span>Centroid</span><strong>{metrics.centroid ? `${formatCoordinate(metrics.centroid[0], "N", "S")}, ${formatCoordinate(metrics.centroid[1], "E", "W")}` : "—"}</strong></article>
      <article><Route size={17} /><span>Mean probability</span><strong>{satellite ? `${(meanProbability * 100).toFixed(1)}%` : "—"}</strong></article>
    </section>

    <section className="simulation-comparison" aria-labelledby="simulation-comparison-title">
      <header><div><p className="eyebrow">Drift reconstruction</p><h3 id="simulation-comparison-title">Backward origin vs forward impact</h3></div><div className="simulation-key"><span className="simulation-key__backward">Hindcast</span><span className="simulation-key__forward">Forecast</span></div></header>
      <div className="simulation-comparison__grid"><article><h4>Where the slick came from</h4><MiniTrajectory drift={backwardDrift} label="Backward hindcast" color="#f4c969" /></article><article><h4>Where the slick may travel</h4><MiniTrajectory drift={forwardDrift} label="Forward forecast" color="#7fd1ff" /></article></div>
    </section>

    <div className="story-grid">
      <section className="distance-panel" aria-labelledby="distance-panel-title"><header><div><p className="eyebrow">Vessel correlation</p><h3 id="distance-panel-title">Distance to estimated origin over time</h3></div><Route size={18} /></header>
        {candidates.length === 0 ? <p className="panel-empty">Run vessel attribution to compare every AIS track against the hindcast origin.</p> : <div className="distance-chart-grid">{candidates.map((candidate) => {
          const data = trackPositions(candidate).map((position) => ({ time: new Date(position.timestamp).getTime(), distance: position.distance_to_origin_km }));
          return <article key={candidate.mmsi} className="distance-chart"><div><strong>MMSI {candidate.mmsi}</strong><span>{candidate.vessel_type ?? "Unknown"} · {(candidate.evidence_score * 100).toFixed(1)} score</span></div><ResponsiveContainer width="100%" height={145}><LineChart data={data} margin={{ top: 10, right: 12, bottom: 4, left: -15 }}><CartesianGrid stroke="rgba(140,200,220,.09)" vertical={false} /><XAxis dataKey="time" type="number" domain={["dataMin", "dataMax"]} tickFormatter={(value) => new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} tick={{ fill: "#7297a6", fontSize: 9 }} /><YAxis unit=" km" tick={{ fill: "#7297a6", fontSize: 9 }} /><Tooltip labelFormatter={(value) => new Date(Number(value)).toLocaleString()} formatter={(value) => [`${Number(value).toFixed(2)} km`, "Distance"]} contentStyle={{ background: "#0a2434", border: "1px solid rgba(140,200,220,.22)", borderRadius: 8 }} /><Line type="monotone" dataKey="distance" stroke={scoreToColor(candidate.evidence_score * 100)} strokeWidth={2.5} dot={false} /></LineChart></ResponsiveContainer></article>;
        })}</div>}
      </section>

      <section className="investigation-timeline" aria-labelledby="investigation-timeline-title"><header><div><p className="eyebrow">Chain of analysis</p><h3 id="investigation-timeline-title">Investigation timeline</h3></div><Timer size={18} /></header><ol>{timeline.map((event, index) => <li key={`${event.title}-${index}`} className={event.complete ? "timeline-complete" : ""}><i /><div><strong>{event.title}</strong><span>{event.detail}</span>{event.time && <time>{new Date(event.time).toLocaleString()}</time>}</div></li>)}</ol></section>
    </div>
  </div>;
}
