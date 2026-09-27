import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { X } from "lucide-react";

import { api } from "../lib/api";
import { computeCentroid } from "../lib/geo";
import type { AttributionResponse, DriftResponse, IngestionResponse, InvestigationSummary, SatelliteDetectionResponse } from "../types/api";

const STAGES = [
  "Create case", "Upload satellite scene", "Segment slick", "Calculate geometry",
  "Obtain environmental data", "Run hindcast", "Run forecast", "Filter AIS traffic",
  "Rank candidates", "Generate signed report",
] as const;
type StageStatus = "waiting" | "running" | "complete" | "failed";

interface Props {
  open: boolean;
  onClose: () => void;
  onComplete: (investigationId: string) => void;
}

function message(error: unknown) {
  return error instanceof Error ? error.message : "The workflow stopped unexpectedly.";
}

export function FullInvestigationWorkflow({ open, onClose, onComplete }: Props) {
  const [title, setTitle] = useState("");
  const [satelliteFile, setSatelliteFile] = useState<File | null>(null);
  const [environmentFile, setEnvironmentFile] = useState<File | null>(null);
  const [aisFile, setAisFile] = useState<File | null>(null);
  const [observedAt, setObservedAt] = useState("");
  const [bounds, setBounds] = useState({ west: "-88.8509434", south: "29.0606100", east: "-88.4597525", north: "29.2801243" });
  const [statuses, setStatuses] = useState<StageStatus[]>(STAGES.map(() => "waiting"));
  const [activeStage, setActiveStage] = useState(-1);
  const activeStageRef = useRef(-1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [finished, setFinished] = useState(false);

  const investigation = useRef<InvestigationSummary | null>(null);
  const satellite = useRef<SatelliteDetectionResponse | null>(null);
  const environment = useRef<IngestionResponse | null>(null);
  const backward = useRef<DriftResponse | null>(null);
  const forward = useRef<DriftResponse | null>(null);
  const ais = useRef<IngestionResponse | null>(null);
  const attribution = useRef<AttributionResponse | null>(null);

  if (!open) return null;

  function stage(index: number, status: StageStatus) {
    activeStageRef.current = index;
    setActiveStage(index);
    setStatuses((current) => current.map((value, position) => position === index ? status : value));
  }

  async function run(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (!satelliteFile || !environmentFile || !aisFile) { setError("Select satellite, environmental, and AIS evidence files."); return; }
    const observation = new Date(observedAt);
    if (!Number.isFinite(observation.getTime())) { setError("Enter the satellite observation date and time."); return; }
    setBusy(true); setError(null); setFinished(false);
    try {
      if (!investigation.current) {
        stage(0, "running");
        investigation.current = await api.createInvestigation({ title: title.trim() });
        stage(0, "complete");
      }
      const caseId = investigation.current.id;
      if (!satellite.current) {
        stage(1, "running");
        const isPng = satelliteFile.name.toLowerCase().endsWith(".png");
        const parsedBounds = isPng ? { west: Number(bounds.west), south: Number(bounds.south), east: Number(bounds.east), north: Number(bounds.north) } : undefined;
        if (parsedBounds && Object.values(parsedBounds).some((value) => !Number.isFinite(value))) throw new Error("PNG evidence requires valid west, south, east, and north bounds.");
        satellite.current = await api.uploadSatellite(caseId, satelliteFile, { bounds: parsedBounds, threshold: 0.5, minComponentPixels: 0 });
        stage(1, "complete"); stage(2, "complete"); stage(3, "complete");
      }
      const centroid = computeCentroid(satellite.current.geojson);
      if (!centroid) throw new Error("Segmentation produced no usable spill geometry.");
      if (!environment.current) {
        stage(4, "running");
        environment.current = await api.uploadEnvironment(caseId, environmentFile);
        stage(4, "complete");
      }
      const driftRequest = {
        environmental_asset_id: environment.current.asset.id, latitude: centroid[0], longitude: centroid[1],
        observed_at: observation.toISOString(), duration_hours: 24, step_minutes: 30, particle_count: 200,
        initial_spread_meters: 250, windage_factor: 0.03, random_seed: 42,
      };
      if (!backward.current) { stage(5, "running"); backward.current = await api.driftBackward(driftRequest); stage(5, "complete"); }
      if (!forward.current) { stage(6, "running"); forward.current = await api.driftForward({ ...driftRequest, duration_hours: 48 }); stage(6, "complete"); }
      if (!ais.current) { stage(7, "running"); ais.current = await api.uploadAis(caseId, aisFile); stage(7, "complete"); }
      if (!attribution.current) {
        const origin = backward.current.trajectory.features.at(-1);
        if (origin?.geometry.type !== "Point" || !origin.properties?.timestamp) throw new Error("Hindcast returned no usable origin for vessel ranking.");
        stage(8, "running");
        attribution.current = await api.rankSuspects({
          ais_asset_id: ais.current.asset.id, origin_latitude: origin.geometry.coordinates[1], origin_longitude: origin.geometry.coordinates[0],
          estimated_origin_at: String(origin.properties.timestamp), search_radius_km: 25, temporal_window_minutes: 90,
          behavior_window_hours: 24, use_hindcast_region: true,
        });
        stage(8, "complete");
      }
      stage(9, "running");
      await api.downloadForensicPackage({ investigation_id: caseId });
      stage(9, "complete"); setFinished(true); onComplete(caseId);
    } catch (caught) {
      setStatuses((current) => current.map((value, index) => index === activeStageRef.current ? "failed" : value));
      setError(message(caught));
    } finally { setBusy(false); }
  }

  return <div className="modal-backdrop" role="presentation">
    <div className="modal full-workflow-modal" role="dialog" aria-modal="true" aria-labelledby="full-workflow-title">
      <header className="modal__header"><h2 id="full-workflow-title">Run full investigation</h2><button type="button" className="modal__close" onClick={onClose} disabled={busy} aria-label="Close full investigation"><X size={18} /></button></header>
      <form className="modal__form" onSubmit={(event) => void run(event)}>
        <p>Select the complete evidence set once. SeaScan will create the case, process every stage, and download the signed report package.</p>
        <label>Investigation title<input required minLength={3} value={title} disabled={Boolean(investigation.current)} onChange={(event) => setTitle(event.target.value)} /></label>
        <label className="modal__file-label"><span>Satellite scene (.tif, .tiff, .png)</span><input required type="file" accept=".tif,.tiff,.png" onChange={(event) => setSatelliteFile(event.target.files?.[0] ?? null)} /></label>
        {satelliteFile?.name.toLowerCase().endsWith(".png") && <div className="modal__bounds-grid">{(["west", "south", "east", "north"] as const).map((name) => <label key={name}><span>{name}</span><input type="number" step="any" required value={bounds[name]} onChange={(event) => setBounds((current) => ({ ...current, [name]: event.target.value }))} /></label>)}</div>}
        <label className="modal__file-label"><span>Environmental current/wind CSV</span><input required type="file" accept=".csv,.parquet,.nc,.netcdf" onChange={(event) => setEnvironmentFile(event.target.files?.[0] ?? null)} /></label>
        <label className="modal__file-label"><span>AIS traffic CSV</span><input required type="file" accept=".csv,.parquet" onChange={(event) => setAisFile(event.target.files?.[0] ?? null)} /></label>
        <label>Satellite observation time (local)<input required type="datetime-local" value={observedAt} onChange={(event) => setObservedAt(event.target.value)} /></label>
        <button type="submit" className="modal__submit" disabled={busy || finished}>{busy ? "Investigation running…" : error ? "Retry from failed stage" : "Run full investigation"}</button>
      </form>
      <ol className="full-workflow-progress" aria-live="polite">{STAGES.map((label, index) => <li key={label} data-status={statuses[index]}><span>{label}</span><strong>{statuses[index]}</strong></li>)}</ol>
      {error && <p className="modal__message modal__message--error">Stage {activeStage + 1} stopped: {error} Completed stages are saved; correct the input and retry.</p>}
      {finished && <p className="modal__message modal__message--success">Full investigation completed. The signed evidence package has been downloaded.</p>}
    </div>
  </div>;
}
