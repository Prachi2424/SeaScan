import { useState } from "react";
import type { FormEvent } from "react";
import { Anchor, Satellite, Waves, X } from "lucide-react";

import { api, ApiError } from "../lib/api";
import type { IngestionResponse, SatelliteDetectionResponse } from "../types/api";

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
  onSatelliteUploaded: (response: SatelliteDetectionResponse) => void;
  onAisUploaded: (response: IngestionResponse) => void;
  onEnvironmentUploaded: (response: IngestionResponse) => void;
  acceptedFormats: AcceptedFormats;
}

const TABS: { key: UploadTab; label: string; icon: typeof Satellite; hint: string }[] = [
  { key: "satellite", label: "Satellite GeoTIFF", icon: Satellite, hint: "Real SAR/optical raster for U-Net spill segmentation." },
  { key: "ais", label: "AIS CSV", icon: Anchor, hint: "Real AIS position export for suspect vessel ranking." },
  { key: "environment", label: "Current / Wind CSV", icon: Waves, hint: "Real oceanographic vector observations for drift modelling." },
];

interface TabState {
  file: File | null;
  submitting: boolean;
  error: string | null;
  successMessage: string | null;
}

const EMPTY_TAB_STATE: TabState = { file: null, submitting: false, error: null, successMessage: null };

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
  const [threshold, setThreshold] = useState(0.5);
  const [useManualBounds, setUseManualBounds] = useState(false);
  const [bounds, setBounds] = useState({ west: "", south: "", east: "", north: "" });

  if (!open) return null;

  function updateTab(tab: UploadTab, patch: Partial<TabState>) {
    setTabState((previous) => ({ ...previous, [tab]: { ...previous[tab], ...patch } }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>, tab: UploadTab) {
    event.preventDefault();
    const file = tabState[tab].file;
    if (!file) {
      updateTab(tab, { error: "Choose a real evidence file before uploading." });
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
        const response = await api.uploadSatellite(investigationId, file, { threshold, bounds: manualBounds });
        onSatelliteUploaded(response);
        updateTab(tab, {
          submitting: false,
          successMessage: `Segmented ${response.validation.component_count as number} spill component(s) from the real raster.`,
        });
      } else if (tab === "ais") {
        const response = await api.uploadAis(investigationId, file);
        onAisUploaded(response);
        updateTab(tab, { submitting: false, successMessage: `AIS evidence stored (${response.asset.byte_size.toLocaleString()} bytes).` });
      } else {
        const response = await api.uploadEnvironment(investigationId, file);
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
                <span>Real data file{accepted.length > 0 ? ` (${accepted.join(", ")})` : ""}</span>
                <input
                  type="file"
                  accept={accepted.join(",")}
                  onChange={(event) => updateTab(key, { file: event.target.files?.[0] ?? null, error: null, successMessage: null })}
                />
              </label>

              {key === "satellite" && (
                <>
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
                </>
              )}

              {state.error && <p className="modal__message modal__message--error">{state.error}</p>}
              {state.successMessage && <p className="modal__message modal__message--success">{state.successMessage}</p>}

              <button type="submit" className="modal__submit" disabled={state.submitting}>
                {state.submitting ? "Uploading real data…" : "Upload to SeaScan backend"}
              </button>
            </form>
          );
        })}
      </div>
    </div>
  );
}
