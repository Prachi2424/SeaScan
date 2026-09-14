import { ShieldAlert } from "lucide-react";

import type { AttributionResponse, CandidateVessel } from "../types/api";
import { scoreToColor } from "../lib/geo";

const BREAKDOWN_LABELS: Record<keyof CandidateVessel["score_breakdown"], string> = {
  proximity: "Proximity",
  temporal: "Temporal",
  trajectory: "Trajectory match",
  behavioral_anomaly: "Behavioral anomaly",
  ais_consistency: "AIS consistency",
  vessel_type: "Vessel type",
};

interface SuspectVesselPanelProps {
  attribution: AttributionResponse | null;
  isLoading: boolean;
  error: string | null;
  selectedMmsi: string | null;
  onSelectVessel: (mmsi: string) => void;
}

export function SuspectVesselPanel({ attribution, isLoading, error, selectedMmsi, onSelectVessel }: SuspectVesselPanelProps) {
  return (
    <aside className="suspect-panel" aria-label="Ranked suspect vessels">
      <header className="suspect-panel__header">
        <ShieldAlert size={18} aria-hidden="true" />
        <div>
          <h2>Suspect vessels</h2>
          <p>Ranked by explainable evidence score</p>
        </div>
      </header>

      {isLoading && <p className="suspect-panel__status">Scoring AIS candidates against the origin window…</p>}
      {error && !isLoading && <p className="suspect-panel__status suspect-panel__status--error">{error}</p>}

      {!isLoading && !error && attribution && attribution.candidates.length === 0 && (
        <p className="suspect-panel__status">No AIS vessels fell inside the search radius and temporal window for this origin estimate.</p>
      )}

      {!isLoading && !error && attribution && attribution.candidates.length > 0 && (
        <>
          <ol className="suspect-list">
            {attribution.candidates.map((candidate, index) => {
              const overallScore = Math.round(candidate.evidence_score * 100);
              const isSelected = candidate.mmsi === selectedMmsi;
              return (
                <li key={candidate.mmsi}>
                  <button
                    type="button"
                    className={`suspect-card ${isSelected ? "suspect-card--selected" : ""}`}
                    onClick={() => onSelectVessel(candidate.mmsi)}
                    aria-pressed={isSelected}
                  >
                    <div className="suspect-card__top">
                      <span className="suspect-card__rank">#{index + 1}</span>
                      <div className="suspect-card__identity">
                        <strong>MMSI {candidate.mmsi}</strong>
                        <span>{candidate.vessel_type ?? "Vessel type unreported"}</span>
                      </div>
                      <span className="suspect-card__score" style={{ color: scoreToColor(overallScore) }}>
                        {overallScore}
                        <small>/100</small>
                      </span>
                    </div>

                    <div className="suspect-card__breakdown">
                      {(Object.keys(BREAKDOWN_LABELS) as (keyof CandidateVessel["score_breakdown"])[]).map((key) => {
                        const value = candidate.score_breakdown[key] ?? 0;
                        const percent = Math.round(value * 100);
                        return (
                          <div className="score-bar" key={key}>
                            <span className="score-bar__label">{BREAKDOWN_LABELS[key]}</span>
                            <div className="score-bar__track">
                              <div className="score-bar__fill" style={{ width: `${percent}%`, background: scoreToColor(percent) }} />
                            </div>
                            <span className="score-bar__value">{percent}</span>
                          </div>
                        );
                      })}
                    </div>

                    <dl className="suspect-card__evidence">
                      <div>
                        <dt>Closest approach</dt>
                        <dd>{candidate.evidence.closest_observed_distance_km.toFixed(2)} km</dd>
                      </div>
                      <div>
                        <dt>Positions in window</dt>
                        <dd>{candidate.evidence.positions_in_time_window}</dd>
                      </div>
                      <div>
                        <dt>Max AIS gap</dt>
                        <dd>{Number.isFinite(candidate.evidence.maximum_ais_gap_minutes) ? `${candidate.evidence.maximum_ais_gap_minutes.toFixed(0)} min` : "n/a"}</dd>
                      </div>
                    </dl>
                  </button>
                </li>
              );
            })}
          </ol>
          <p className="suspect-panel__disclaimer">{attribution.disclaimer}</p>
        </>
      )}

      {!isLoading && !error && !attribution && (
        <p className="suspect-panel__status">Run AIS attribution to rank candidate vessels once a spill origin has been estimated.</p>
      )}
    </aside>
  );
}
