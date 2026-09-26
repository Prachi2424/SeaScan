import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../lib/api";
import { runWorkflow } from "../lib/workflow";
import type { AttributionResponse, DriftResponse, IngestionResponse, SatelliteDetectionResponse } from "../types/api";

interface Props {
  satellite: SatelliteDetectionResponse | null;
  environment: IngestionResponse | null;
  ais: IngestionResponse | null;
  centroid: [number, number] | null;
  disabled: boolean;
  onBusy: (busy: boolean) => void;
  onBackward: (result: DriftResponse) => void;
  onForward: (result: DriftResponse) => void;
  onAttribution: (result: AttributionResponse) => void;
}
const stages = ["Evidence ready", "Backward hindcast", "Forward forecast", "Vessel ranking"];

export function AnalysisWorkflow({ satellite, environment, ais, centroid, disabled, onBusy, onBackward, onForward, onAttribution }: Props) {
  const running = useRef(false);
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState(-1);
  const [error, setError] = useState<string | null>(null);
  const [complete, setComplete] = useState(false);
  const [observedAt, setObservedAt] = useState("");
  const [backwardHours, setBackwardHours] = useState(24);
  const [forwardHours, setForwardHours] = useState(48);
  const [radius, setRadius] = useState(25);
  const [minutes, setMinutes] = useState(90);
  const missing = [!satellite && "satellite imagery", !environment && "environmental data", !ais && "AIS data"].filter(Boolean);
  const noSpill = satellite && (!satellite.geojson.features.length || !centroid);

  async function run(event: FormEvent) {
    event.preventDefault();
    if (running.current || disabled || !satellite || !environment || !ais || !centroid || noSpill) return;
    const time = new Date(observedAt);
    if (!Number.isFinite(time.getTime())) { setError("Enter the satellite image observation time."); return; }
    running.current = true;
    setBusy(true); onBusy(true); setError(null); setComplete(false); setStage(0);
    try {
      await runWorkflow(api, {
        environmental_asset_id: environment.asset.id,
        latitude: centroid[0], longitude: centroid[1], observed_at: time.toISOString(),
        duration_hours: backwardHours, step_minutes: 30, particle_count: 200,
        initial_spread_meters: 250, windage_factor: 0.03, random_seed: 42,
      }, forwardHours, {
        ais_asset_id: ais.asset.id, search_radius_km: radius,
        temporal_window_minutes: minutes, behavior_window_hours: 24,
      }, (next) => setStage({ hindcast: 1, forecast: 2, ranking: 3 }[next]), {
        backward: onBackward, forward: onForward, attribution: onAttribution,
      });
      setComplete(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Analysis failed.");
    } finally { running.current = false; setBusy(false); onBusy(false); }
  }

  return <section className="controls-card" aria-labelledby="workflow-title">
    <h2 id="workflow-title">Run complete analysis</h2>
    <p>Detection and spill measurements are saved during satellite upload. Continue from the detected spill centroid through drift and vessel ranking.</p>
    {missing.length > 0 && <p role="status">Upload {missing.join(", ")} to begin.</p>}
    {noSpill && <p role="alert">No usable spill geometry was detected. Review the satellite evidence before running drift.</p>}
    <form onSubmit={(event) => void run(event)}>
      <fieldset disabled={busy || disabled} className="workflow-fields">
        <div className="controls-card__grid">
          <label><span>Satellite observation time (local)</span><input type="datetime-local" required value={observedAt} onChange={(event) => setObservedAt(event.target.value)} /></label>
          <label><span>Hindcast window (hours)</span><input type="number" required min={1} max={168} value={backwardHours} onChange={(event) => setBackwardHours(Number(event.target.value))} /></label>
          <label><span>Forecast window (hours)</span><input type="number" required min={1} max={168} value={forwardHours} onChange={(event) => setForwardHours(Number(event.target.value))} /></label>
          <label><span>Vessel search radius (km)</span><input type="number" required min={1} max={500} value={radius} onChange={(event) => setRadius(Number(event.target.value))} /></label>
          <label><span>Vessel time window (± minutes)</span><input type="number" required min={5} max={1440} value={minutes} onChange={(event) => setMinutes(Number(event.target.value))} /></label>
        </div>
        <p>Uses 200 particles, 30-minute drift steps, 250 m initial spread, 3% windage and a 24-hour behavior window. The hindcast window is a chosen scenario, not an inferred spill age.</p>
        <button className="primary-button" type="submit" disabled={missing.length > 0 || Boolean(noSpill)}>{busy ? "Analysis running…" : "Run analysis"}</button>
      </fieldset>
    </form>
    <ol aria-live="polite">{stages.map((label, index) => <li key={label}>{label}: {complete || index < stage ? "Complete" : index === stage ? error ? "Stopped" : "Running" : "Waiting"}</li>)}</ol>
    {busy && <p role="status">Keep this page open. Each successful stage is saved automatically.</p>}
    {error && <p role="alert">{stages[stage]} stopped: {error} Completed stages remain saved. Correct the input and run again. Older results below may belong to a previous run.</p>}
    {complete && <p role="status">Analysis complete and saved. Review results below, then export the PDF or evidence package. Zero matching vessels is a valid result.</p>}
  </section>;
}
