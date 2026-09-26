import { useState } from "react";
import type { FormEvent } from "react";
import { CornerUpLeft, CornerUpRight, LocateFixed } from "lucide-react";

import type { DriftRequest, DriftResponse, IngestionResponse } from "../types/api";

interface DriftControlsProps {
  savedBackward?: DriftResponse | null;
  savedForward?: DriftResponse | null;
  environmentAsset: IngestionResponse | null;
  spillCentroid: [number, number] | null; // [lat, lng]
  onRunBackward: (payload: DriftRequest) => void;
  onRunForward: (payload: DriftRequest) => void;
  backwardLoading: boolean;
  forwardLoading: boolean;
  backwardError: string | null;
  forwardError: string | null;
  backwardResult: DriftResponse | null;
  forwardResult?: DriftResponse | null;
}

function nowForDatetimeLocal(): string {
  const now = new Date();
  now.setSeconds(0, 0);
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function toIsoFromLocalInput(value: string): string {
  return new Date(value).toISOString();
}

export function DriftControls({
  savedBackward,
  savedForward,
  environmentAsset,
  spillCentroid,
  onRunBackward,
  onRunForward,
  backwardLoading,
  forwardLoading,
  backwardError,
  forwardError,
  backwardResult,
  forwardResult,
}: DriftControlsProps) {
  const saved = (savedBackward?.parameters ?? savedForward?.parameters ?? savedBackward?.seed ?? savedForward?.seed ?? {}) as Partial<DriftRequest>;
  const [latitude, setLatitude] = useState(saved.latitude !== undefined ? String(saved.latitude) : spillCentroid ? String(spillCentroid[0]) : "");
  const [longitude, setLongitude] = useState(saved.longitude !== undefined ? String(saved.longitude) : spillCentroid ? String(spillCentroid[1]) : "");
  const [observedAt, setObservedAt] = useState(() => {
    if (!saved.observed_at) return nowForDatetimeLocal();
    const date = new Date(saved.observed_at);
    return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  });
  const [backwardHours, setBackwardHours] = useState(savedBackward?.parameters?.duration_hours ?? Number(savedBackward?.seed.duration_hours ?? 24));
  const [forwardHours, setForwardHours] = useState(savedForward?.parameters?.duration_hours ?? Number(savedForward?.seed.duration_hours ?? 48));
  const [particleCount, setParticleCount] = useState(saved.particle_count ?? 200);
  const [initialSpreadMeters, setInitialSpreadMeters] = useState(saved.initial_spread_meters ?? 250);
  const [windageFactor, setWindageFactor] = useState(saved.windage_factor ?? 0.03);
  const [stepMinutes, setStepMinutes] = useState(saved.step_minutes ?? 30);

  const disabled = !environmentAsset;

  function applySpillCentroid() {
    if (!spillCentroid) return;
    setLatitude(String(spillCentroid[0]));
    setLongitude(String(spillCentroid[1]));
  }

  function buildPayload(durationHours: number): DriftRequest | null {
    if (!environmentAsset) return null;
    const lat = Number.parseFloat(latitude);
    const lng = Number.parseFloat(longitude);
    if (Number.isNaN(lat) || Number.isNaN(lng)) return null;
    return {
      environmental_asset_id: environmentAsset.asset.id,
      latitude: lat,
      longitude: lng,
      observed_at: toIsoFromLocalInput(observedAt),
      duration_hours: durationHours,
      step_minutes: stepMinutes,
      particle_count: particleCount,
      initial_spread_meters: initialSpreadMeters,
      windage_factor: windageFactor,
      random_seed: 42,
    };
  }

  function handleBackwardSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const payload = buildPayload(backwardHours);
    if (payload) onRunBackward(payload);
  }

  function handleForwardSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const payload = buildPayload(forwardHours);
    if (payload) onRunForward(payload);
  }

  return (
    <section className="controls-card" aria-labelledby="drift-controls-title">
      <header className="controls-card__header">
        <h2 id="drift-controls-title">Environmental drift modelling</h2>
        {!environmentAsset && <p className="controls-card__notice">Upload a current/wind CSV to enable hindcasting and forecasting.</p>}
      </header>

      <div className="controls-card__grid">
        <label>
          <span>Observed latitude</span>
          <input type="number" step="any" value={latitude} onChange={(event) => setLatitude(event.target.value)} disabled={disabled} required />
        </label>
        <label>
          <span>Observed longitude</span>
          <input type="number" step="any" value={longitude} onChange={(event) => setLongitude(event.target.value)} disabled={disabled} required />
        </label>
        <button type="button" className="controls-card__inline-button" onClick={applySpillCentroid} disabled={!spillCentroid}>
          <LocateFixed size={14} /> Use spill centroid
        </button>
        <label>
          <span>Observed at (local time)</span>
          <input type="datetime-local" value={observedAt} onChange={(event) => setObservedAt(event.target.value)} disabled={disabled} required />
        </label>
        <label>
          <span>Step (minutes)</span>
          <input type="number" min={5} max={120} value={stepMinutes} onChange={(event) => setStepMinutes(Number.parseInt(event.target.value, 10))} disabled={disabled} />
        </label>
        <label>
          <span>Particle count</span>
          <input type="number" min={20} max={1000} value={particleCount} onChange={(event) => setParticleCount(Number.parseInt(event.target.value, 10))} disabled={disabled} />
        </label>
        <label>
          <span>Initial spread (m)</span>
          <input type="number" min={0} max={10000} value={initialSpreadMeters} onChange={(event) => setInitialSpreadMeters(Number.parseFloat(event.target.value))} disabled={disabled} />
        </label>
        <label>
          <span>Windage factor</span>
          <input type="number" min={0} max={0.1} step={0.005} value={windageFactor} onChange={(event) => setWindageFactor(Number.parseFloat(event.target.value))} disabled={disabled} />
        </label>
      </div>

      <div className="controls-card__actions">
        <form onSubmit={handleBackwardSubmit} className="controls-card__action-form">
          <label>
            <span>Hindcast window (hours)</span>
            <input type="number" min={1} max={168} value={backwardHours} onChange={(event) => setBackwardHours(Number.parseFloat(event.target.value))} disabled={disabled} />
          </label>
          <button type="submit" disabled={disabled || backwardLoading}>
            <CornerUpLeft size={15} /> {backwardLoading ? "Hindcasting…" : "Run backward hindcast"}
          </button>
          {backwardError && <p className="controls-card__error">{backwardError}</p>}
        </form>

        <form onSubmit={handleForwardSubmit} className="controls-card__action-form">
          <label>
            <span>Forecast window (hours)</span>
            <input type="number" min={1} max={168} value={forwardHours} onChange={(event) => setForwardHours(Number.parseFloat(event.target.value))} disabled={disabled} />
          </label>
          <button type="submit" disabled={disabled || forwardLoading}>
            <CornerUpRight size={15} /> {forwardLoading ? "Forecasting…" : "Run forward prediction"}
          </button>
          {forwardError && <p className="controls-card__error">{forwardError}</p>}
        </form>
      </div>

      {[backwardResult, forwardResult].filter((result): result is DriftResponse => Boolean(result)).map((result) => (
        <div key={result.direction} role="status">
          <p>{result.direction === "backward" ? "Hindcast" : "Forecast"}: {String(result.sampling.method)}. Maximum distance to observations: {String(result.sampling.maximum_nearest_observation_distance_km ?? "Not recorded")} km.</p>
          {Array.isArray(result.sampling.warnings) && result.sampling.warnings.map((warning, index) => <p key={index} className="controls-card__notice">{String(warning)}</p>)}
        </div>
      ))}

      {backwardResult && (
        <p className="controls-card__result">
          Maximum environmental sampling gap: {String(backwardResult.sampling.maximum_time_gap_minutes)} minutes. Estimated origin sits at the
          final point of the hindcast trajectory below.
        </p>
      )}
    </section>
  );
}
