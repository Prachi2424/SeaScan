import { useRef, useState } from "react";
import { api } from "../lib/api";
import type { ReleaseScenarioResponse } from "../types/api";

export function ReleaseScenarios({ environmentId, aisId, centroid, result, onResult, disabled, onBusy }: {
  environmentId?: string; aisId?: string; centroid: [number, number] | null;
  result: ReleaseScenarioResponse | null; onResult: (result: ReleaseScenarioResponse) => void;
  disabled: boolean; onBusy: (value: boolean) => void;
}) {
  const [time, setTime] = useState("");
  const [durations, setDurations] = useState("6, 12, 24");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const running = useRef(false);
  const ready = Boolean(environmentId && aisId && centroid);
  return <section className="controls-card" aria-labelledby="release-title">
    <h2 id="release-title">Explore release-time scenarios</h2>
    <p>Compare selected hindcast durations with AIS evidence. This does not estimate a validated spill age or confidence percentage. Your main drift and ranking results stay separate.</p>
    {!ready && <p>Upload environmental and AIS evidence and detect a spill to enable comparison.</p>}
    <form onSubmit={async (event) => {
      event.preventDefault();
      if (running.current || disabled || !environmentId || !aisId || !centroid) return;
      const values = durations.split(",").map((value) => Number(value.trim()));
      if (!values.length || values.length > 5 || new Set(values).size !== values.length || values.some((value) => !Number.isFinite(value) || value < 1 || value > 72)) {
        setError("Enter up to five unique durations from 1 to 72 hours, separated by commas."); return;
      }
      if (!Number.isFinite(Date.parse(time))) { setError("Enter the image observation time."); return; }
      setError(null); running.current = true; setBusy(true); onBusy(true);
      try {
        onResult(await api.releaseScenarios({ ais_asset_id: aisId, durations_hours: values, search_radius_km: 25, temporal_window_minutes: 90,
          drift: { environmental_asset_id: environmentId, latitude: centroid[0], longitude: centroid[1], observed_at: new Date(time).toISOString(),
            duration_hours: values[0], particle_count: 100, step_minutes: 30, initial_spread_meters: 250, windage_factor: .03, random_seed: 42 } }));
      } catch (caught) { setError(caught instanceof Error ? caught.message : "Comparison failed."); }
      finally { running.current = false; setBusy(false); onBusy(false); }
    }}>
      <fieldset className="workflow-fields" disabled={disabled || busy || !ready}>
        <div className="controls-card__grid">
          <label><span>Image observation time (local)</span><input type="datetime-local" required value={time} onChange={(event) => setTime(event.target.value)} /></label>
          <label><span>Durations to compare (hours)</span><input required value={durations} onChange={(event) => setDurations(event.target.value)} /></label>
        </div>
        <p>100 particles · 30-minute steps · 250 m spread · 3% windage · 25 km vessel radius · ±90-minute search · 24-hour behavior window.</p>
        <button type="submit" className="primary-button">{busy ? "Comparing scenarios…" : "Compare release times"}</button>
      </fieldset>
    </form>
    {busy && <p role="status">Keep this page open while up to five scenarios are compared.</p>}
    {error && <p role="alert">{error} Any comparison below is the previously saved result.</p>}
    {result && <div aria-live="polite">
      <p>{result.disclaimer}</p>
      <p>Saved comparison: observed {new Date(result.parameters.drift.observed_at).toLocaleString()} · durations {result.parameters.durations_hours.join(", ")} hours.</p>
      {result.scenarios.map((scenario) => <article key={scenario.duration_hours}>
        <h3>{scenario.duration_hours} hours before observation</h3>
        {scenario.status !== "complete" ? <p>Unavailable: {scenario.error}</p> : <>
          <p>Origin time: {String(scenario.origin?.properties?.timestamp)} · origin (longitude, latitude): {scenario.origin?.geometry.coordinates.map((value) => value.toFixed(5)).join(", ")}</p>
          <p>{scenario.candidate_count} matching vessels. {scenario.candidates?.length ? `Leading candidate: ${scenario.candidates[0].mmsi}, evidence score ${scenario.candidates[0].evidence_score.toFixed(3)}.` : "No candidates in the selected search window."}</p>
          {scenario.sampling?.warnings?.map((warning, index) => <p key={index}>{warning}</p>)}
          <details><summary>Candidate evidence</summary>{scenario.candidates?.slice(0, 3).map((candidate) => <p key={candidate.mmsi}>MMSI {candidate.mmsi}: closest approach {candidate.evidence.closest_approach_distance_km?.toFixed(2)} km at {candidate.evidence.closest_approach_at}; region intersection {String(candidate.evidence.origin_region_intersection)}. {candidate.evidence.warnings?.join(" ")}</p>)}</details>
        </>}
      </article>)}
    </div>}
  </section>;
}
