import { useState } from "react";
import type { FormEvent } from "react";
import { Crosshair, ScanSearch } from "lucide-react";

import type { AttributionRequest, IngestionResponse } from "../types/api";

interface SuggestedOrigin {
  latitude: number;
  longitude: number;
  estimatedOriginAt: string; // ISO timestamp
}

interface AttributionControlsProps {
  aisAsset: IngestionResponse | null;
  suggestedOrigin: SuggestedOrigin | null;
  onRun: (payload: AttributionRequest) => void;
  loading: boolean;
  error: string | null;
}

function toLocalInputValue(iso: string): string {
  const date = new Date(iso);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

export function AttributionControls({ aisAsset, suggestedOrigin, onRun, loading, error }: AttributionControlsProps) {
  const [originLatitude, setOriginLatitude] = useState(suggestedOrigin ? String(suggestedOrigin.latitude) : "");
  const [originLongitude, setOriginLongitude] = useState(suggestedOrigin ? String(suggestedOrigin.longitude) : "");
  const [estimatedOriginAt, setEstimatedOriginAt] = useState(
    suggestedOrigin ? toLocalInputValue(suggestedOrigin.estimatedOriginAt) : "",
  );
  const [searchRadiusKm, setSearchRadiusKm] = useState(25);
  const [temporalWindowMinutes, setTemporalWindowMinutes] = useState(90);
  const [behaviorWindowHours, setBehaviorWindowHours] = useState(24);

  const disabled = !aisAsset;

  function applySuggestedOrigin() {
    if (!suggestedOrigin) return;
    setOriginLatitude(String(suggestedOrigin.latitude));
    setOriginLongitude(String(suggestedOrigin.longitude));
    setEstimatedOriginAt(toLocalInputValue(suggestedOrigin.estimatedOriginAt));
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!aisAsset) return;
    const lat = Number.parseFloat(originLatitude);
    const lng = Number.parseFloat(originLongitude);
    if (Number.isNaN(lat) || Number.isNaN(lng) || !estimatedOriginAt) return;
    onRun({
      ais_asset_id: aisAsset.asset.id,
      origin_latitude: lat,
      origin_longitude: lng,
      estimated_origin_at: new Date(estimatedOriginAt).toISOString(),
      search_radius_km: searchRadiusKm,
      temporal_window_minutes: temporalWindowMinutes,
      behavior_window_hours: behaviorWindowHours,
    });
  }

  return (
    <section className="controls-card" aria-labelledby="attribution-controls-title">
      <header className="controls-card__header">
        <h2 id="attribution-controls-title">AIS suspect attribution</h2>
        {!aisAsset && <p className="controls-card__notice">Upload an AIS CSV to enable explainable vessel ranking.</p>}
      </header>

      <form onSubmit={handleSubmit} className="controls-card__grid controls-card__grid--attribution">
        <label>
          <span>Origin latitude</span>
          <input type="number" step="any" value={originLatitude} onChange={(event) => setOriginLatitude(event.target.value)} disabled={disabled} required />
        </label>
        <label>
          <span>Origin longitude</span>
          <input type="number" step="any" value={originLongitude} onChange={(event) => setOriginLongitude(event.target.value)} disabled={disabled} required />
        </label>
        <button type="button" className="controls-card__inline-button" onClick={applySuggestedOrigin} disabled={!suggestedOrigin}>
          <Crosshair size={14} /> Use hindcast origin
        </button>
        <label>
          <span>Estimated origin time (local)</span>
          <input type="datetime-local" value={estimatedOriginAt} onChange={(event) => setEstimatedOriginAt(event.target.value)} disabled={disabled} required />
        </label>
        <label>
          <span>Search radius (km)</span>
          <input type="number" min={1} max={500} value={searchRadiusKm} onChange={(event) => setSearchRadiusKm(Number.parseFloat(event.target.value))} disabled={disabled} />
        </label>
        <label>
          <span>Temporal window (minutes)</span>
          <input
            type="number"
            min={5}
            max={1440}
            value={temporalWindowMinutes}
            onChange={(event) => setTemporalWindowMinutes(Number.parseInt(event.target.value, 10))}
            disabled={disabled}
          />
        </label>
        <label>
          <span>Behavior window (hours)</span>
          <input
            type="number"
            min={1}
            max={168}
            value={behaviorWindowHours}
            onChange={(event) => setBehaviorWindowHours(Number.parseInt(event.target.value, 10))}
            disabled={disabled}
          />
        </label>

        <button type="submit" className="controls-card__submit" disabled={disabled || loading}>
          <ScanSearch size={15} /> {loading ? "Ranking AIS candidates…" : "Rank suspect vessels"}
        </button>
      </form>

      {error && <p className="controls-card__error">{error}</p>}
    </section>
  );
}
