import { useState } from "react";
import type { FormEvent } from "react";
import { Anchor, Satellite, Waves, X } from "lucide-react";

import { api, ApiError } from "../lib/api";
import type { EvidenceProvenance, IngestionResponse, SatelliteDetectionResponse, SatellitePresentation } from "../types/api";

type UploadTab = "satellite" | "ais" | "environment";

interface AcceptedFormats {
  satellite: string[];
  ais: string[];
  environment: string[];
}

interface UploadModalProps {
  investigationId: string;
  open: boolean;
  onClose: () => void;
  onSatelliteUploaded: (response: SatelliteDetectionResponse, presentation: SatellitePresentation) => void;
  onAisUploaded: (response: IngestionResponse) => void;
  onEnvironmentUploaded: (response: IngestionResponse) => void;
  acceptedFormats: AcceptedFormats;
}

const TABS: { key: UploadTab; label: string; icon: typeof Satellite; hint: string }[] = [
  { key: "satellite", label: "Satellite GeoTIFF", icon: Satellite, hint: "SAR/optical raster for U-Net spill segmentation." },
  { key: "ais", label: "AIS CSV", icon: Anchor, hint: "AIS position export for suspect vessel ranking." },
  { key: "environment", label: "Current / Wind CSV", icon: Waves, hint: "Oceanographic vector observations for drift modelling." },
];

interface TabState {
  provenance: EvidenceProvenance;
  file: File | null;
  submitting: boolean;
  error: string | null;
  successMessage: string | null;
}

const EMPTY_TAB_STATE: TabState = { provenance: { evidence_kind: "unknown", source_organization: "", source_reference: "", dataset_version: "", acquired_at: null, declared_crs: "", prior_processing: "", added_by: "" }, file: null, submitting: false, error: null, successMessage: null };

export function UploadModal({
  investigationId,
  open,
  onClose,
  onSatelliteUploaded,
  onAisUploaded,
  onEnvironmentUploaded,
  acceptedFormats,
}: UploadModalProps) {
  const [activeTab, setActiveTab] = useState<UploadTab>("satellite");
  const [tabState, setTabState] = useState<Record<UploadTab, TabState>>({
    satellite: { ...EMPTY_TAB_STATE },
    ais: { ...EMPTY_TAB_STATE },
    environment: { ...EMPTY_TAB_STATE },
  });
  const [minComponentPixels, setMinComponentPixels] = useState(0);
  const [threshold, setThreshold] = useState(0.5);
  const [useManualBounds, setUseManualBounds] = useState(false);
  const [bounds, setBounds] = useState({ west: "", south: "", east: "", north: "" });
  const [groundTruthFile, setGroundTruthFile] = useState<File | null>(null);

  if (!open) return null;

  function updateTab(tab: UploadTab, patch: Partial<TabState>) {
    setTabState((previous) => ({ ...previous, [tab]: { ...previous[tab], ...patch } }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>, tab: UploadTab) {
    event.preventDefault();
    const file = tabState[tab].file;
    if (!file) {
      updateTab(tab, { error: "Choose an evidence file before uploading." });
      return;
    }
    updateTab(tab, { submitting: true, error: null, successMessage: null });
    try {
      if (tab === "satellite") {
        let manualBounds: { west: number; south: number; east: number; north: number } | undefined;
        if (useManualBounds) {
          const parsed = {
            west: Number.parseFloat(bounds.west),
            south: Number.parseFloat(bounds.south),
            east: Number.parseFloat(bounds.east),
            north: Number.parseFloat(bounds.north),
          };
          if (Object.values(parsed).some((value) => Number.isNaN(value))) {
            throw new Error("Provide numeric west, south, east, and north bounds to georeference a PNG.");
          }
          manualBounds = parsed;
        }
        const response = await api.uploadSatellite(investigationId, file, { threshold, minComponentPixels, bounds: manualBounds, provenance: tabState[tab].provenance });
        const detectedBounds = manualBounds
          ? ([manualBounds.west, manualBounds.south, manualBounds.east, manualBounds.north] as [number, number, number, number])
          : null;
        onSatelliteUploaded(response, {
          imageUrl: file.type === "image/png" ? URL.createObjectURL(file) : null,
          groundTruthUrl: groundTruthFile ? URL.createObjectURL(groundTruthFile) : null,
          bounds: detectedBounds,
          filename: file.name,
        });
        updateTab(tab, {
          submitting: false,
          successMessage: `Segmented ${response.validation.component_count as number} spill component(s) from the uploaded raster.`,
        });
      } else if (tab === "ais") {
        const response = await api.uploadAis(investigationId, file, tabState[tab].provenance);
        onAisUploaded(response);
        updateTab(tab, { submitting: false, successMessage: `AIS evidence stored (${response.asset.byte_size.toLocaleString()} bytes).` });
      } else {
        const response = await api.uploadEnvironment(investigationId, file, tabState[tab].provenance);
        onEnvironmentUploaded(response);
        updateTab(tab, { submitting: false, successMessage: `Environmental evidence stored (${response.asset.byte_size.toLocaleString()} bytes).` });
      }
    } catch (error) {
      const message = error instanceof ApiError ? error.message : error instanceof Error ? error.message : "Upload failed.";
      updateTab(tab, { submitting: false, error: message });
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="upload-modal-title">
        <header className="modal__header">
          <h2 id="upload-modal-title">Upload investigation evidence</h2>
          <button type="button" className="modal__close" onClick={onClose} aria-label="Close upload modal">
            <X size={18} />
          </button>
        </header>

        <div className="modal__tabs" role="tablist">
          {TABS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={activeTab === key}
              className={`modal__tab ${activeTab === key ? "modal__tab--active" : ""}`}
              onClick={() => setActiveTab(key)}
            >
              <Icon size={16} aria-hidden="true" /> {label}
            </button>
          ))}
        </div>

        {TABS.map(({ key, hint }) => {
          if (key !== activeTab) return null;
          const state = tabState[key];
          const accepted = acceptedFormats[key];
          return (
            <form key={key} className="modal__form" onSubmit={(event) => void handleSubmit(event, key)}>
              <p className="modal__hint">{hint}</p>
              <label className="modal__file-label">
                <span>Evidence file{accepted.length > 0 ? ` (${accepted.join(", ")})` : ""}</span>
                <input
                  type="file"
                  accept={accepted.join(",")}
                  onChange={(event) => updateTab(key, { file: event.target.files?.[0] ?? null, error: null, successMessage: null })}
                />
              </label>

              <fieldset className="provenance-form" disabled={state.submitting}>
                <legend>Evidence provenance</legend>
                <p>These are uploader declarations, not independently verified facts. Leave unknown details blank.</p>
                <label>Evidence type
                  <select value={state.provenance.evidence_kind} onChange={(event) => updateTab(key, { provenance: { ...state.provenance, evidence_kind: event.target.value as EvidenceProvenance["evidence_kind"] } })}>
                    <option value="unknown">Not recorded / unknown</option>
                    <option value="real">Real observations (declared)</option>
                    <option value="synthetic">Synthetic / demonstration</option>
                  </select>
                </label>
                {([
                  ["source_organization", "Source organization", 200],
                  ["source_reference", "Source URL, DOI or reference", 500],
                  ["dataset_version", "Dataset / version", 200],
                  ["declared_crs", "Coordinate reference system (declared)", 120],
                  ["added_by", "Added by (self-reported; not authenticated)", 200],
                ] as const).map(([field, label, maxLength]) => (
                  <label key={field}>{label}<input type="text" maxLength={maxLength} value={state.provenance[field]} onChange={(event) => updateTab(key, { provenance: { ...state.provenance, [field]: event.target.value } })} /></label>
                ))}
                <label>Acquisition timestamp (UTC)
                  <input type="datetime-local" value={state.provenance.acquired_at?.slice(0, 16) ?? ""} onChange={(event) => updateTab(key, { provenance: { ...state.provenance, acquired_at: event.target.value ? `${event.target.value}:00Z` : null } })} />
                </label>
                <label>Processing before upload
                  <textarea maxLength={2000} value={state.provenance.prior_processing} onChange={(event) => updateTab(key, { provenance: { ...state.provenance, prior_processing: event.target.value } })} />
                </label>
              </fieldset>

              {key === "satellite" && (
                <>
                  <label>Minimum spill component size (pixels)
                    <input type="number" min={0} max={1000000} step={1} required value={minComponentPixels} onChange={(event) => setMinComponentPixels(Number(event.target.value))} />
                    <small>0 disables cleanup. Small real spills may also be removed; compare with the unfiltered result.</small>
                  </label>
                  <label className="modal__slider-label">
                    <span>Segmentation threshold ({threshold.toFixed(2)})</span>
                    <input
                      type="range"
                      min={0.05}
                      max={0.95}
                      step={0.01}
                      value={threshold}
                      onChange={(event) => setThreshold(Number.parseFloat(event.target.value))}
                    />
                  </label>
                  <label className="modal__checkbox-label">
                    <input type="checkbox" checked={useManualBounds} onChange={(event) => setUseManualBounds(event.target.checked)} />
                    <span>Georeference a PNG with manual west/south/east/north bounds (required for PNG, ignored for GeoTIFF)</span>
                  </label>
                  {useManualBounds && (
                    <div className="modal__bounds-grid">
                      {(["west", "south", "east", "north"] as const).map((field) => (
                        <label key={field}>
                          <span>{field}</span>
                          <input
                            type="number"
                            step="any"
                            value={bounds[field]}
                            onChange={(event) => setBounds((previous) => ({ ...previous, [field]: event.target.value }))}
                          />
                        </label>
                      ))}
                    </div>
                  )}
                  <label className="modal__file-label">
                    <span>Optional ground-truth mask (validation cases only)</span>
                    <input
                      type="file"
                      accept="image/png"
                      onChange={(event) => setGroundTruthFile(event.target.files?.[0] ?? null)}
                    />
                  </label>
                </>
              )}

              {state.error && <p className="modal__message modal__message--error">{state.error}</p>}
              {state.successMessage && <p className="modal__message modal__message--success">{state.successMessage}</p>}

              <button type="submit" className="modal__submit" disabled={state.submitting}>
                {state.submitting ? "Uploading evidence…" : "Upload to SeaScan backend"}
              </button>
            </form>
          );
        })}
      </div>
    </div>
  );
}
