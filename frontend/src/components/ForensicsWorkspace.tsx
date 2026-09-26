import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Download, FileArchive, FolderPlus, Satellite, ShieldCheck, UploadCloud, Waves } from "lucide-react";

import { api, ApiError } from "../lib/api";
import { computeCentroid } from "../lib/geo";
import type {
  ReleaseScenarioResponse,
  EvidenceAsset,
  AttributionRequest,
  AttributionResponse,
  DriftRequest,
  DriftResponse,
  IngestionResponse,
  InvestigationSummary,
  SatelliteDetectionResponse,
  SatellitePresentation,
} from "../types/api";

import { AttributionControls } from "./AttributionControls";
import { DriftControls } from "./DriftControls";
import { IntelligenceFlowGraph } from "./IntelligenceFlowGraph";
import type { FlowStageKey } from "./IntelligenceFlowGraph";
import { MaritimeMap } from "./MaritimeMap";
import { ForensicStory } from "./ForensicStory";
import { SuspectVesselPanel } from "./SuspectVesselPanel";
import { EvidenceProvenancePanel } from "./EvidenceProvenancePanel";
import { ReleaseScenarios } from "./ReleaseScenarios";
import { AnalysisWorkflow } from "./AnalysisWorkflow";
import { UploadModal } from "./UploadModal";

interface ForensicsWorkspaceProps {
  acceptedFormats: {
    satellite: string[];
    ais: string[];
    environment: string[];
  };
  userRole: "investigator" | "analyst" | "administrator";
}

function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "An unexpected error occurred.";
}

/** The final feature of a backward-hindcast trajectory is the model's earliest, furthest-back estimate. */
function extractHindcastOrigin(drift: DriftResponse): { latitude: number; longitude: number; estimatedOriginAt: string } | null {
  const features = drift.trajectory.features;
  if (features.length === 0) return null;
  const originFeature = features[features.length - 1];
  if (originFeature.geometry.type !== "Point") return null;
  const [longitude, latitude] = originFeature.geometry.coordinates;
  const estimatedOriginAt = String((originFeature.properties ?? {}).timestamp ?? drift.seed.observed_at ?? "");
  if (!estimatedOriginAt) return null;
  return { latitude, longitude, estimatedOriginAt };
}

export function ForensicsWorkspace({ acceptedFormats, userRole }: ForensicsWorkspaceProps) {
  const canManageEvidence = userRole === "investigator" || userRole === "administrator";
  const [investigations, setInvestigations] = useState<InvestigationSummary[]>([]);
  const [investigation, setInvestigation] = useState<InvestigationSummary | null>(null);
  const restoreVersion = useRef(0);
  const [restoring, setRestoring] = useState(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  const [newTitle, setNewTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const [evidenceAssets, setEvidenceAssets] = useState<EvidenceAsset[]>([]);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [satellite, setSatellite] = useState<SatelliteDetectionResponse | null>(null);
  const [satellitePresentation, setSatellitePresentation] = useState<SatellitePresentation | null>(null);
  const satellitePresentationRef = useRef<SatellitePresentation | null>(null);
  const [aisAsset, setAisAsset] = useState<IngestionResponse | null>(null);
  const [environmentAsset, setEnvironmentAsset] = useState<IngestionResponse | null>(null);

  const [backwardDrift, setBackwardDrift] = useState<DriftResponse | null>(null);
  const [forwardDrift, setForwardDrift] = useState<DriftResponse | null>(null);
  const [backwardLoading, setBackwardLoading] = useState(false);
  const [forwardLoading, setForwardLoading] = useState(false);
  const [backwardError, setBackwardError] = useState<string | null>(null);
  const [forwardError, setForwardError] = useState<string | null>(null);

  const [attribution, setAttribution] = useState<AttributionResponse | null>(null);
  const [attributionLoading, setAttributionLoading] = useState(false);
  const [attributionError, setAttributionError] = useState<string | null>(null);

  const [selectedMmsi, setSelectedMmsi] = useState<string | null>(null);
  const [reportLoading, setReportLoading] = useState<"pdf" | "package" | null>(null);
  const [scenarioBusy, setScenarioBusy] = useState(false);
  const [scenarios, setScenarios] = useState<ReleaseScenarioResponse | null>(null);
  const [workflowBusy, setWorkflowBusy] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);


  async function loadInvestigations() {
    setListLoading(true);
    setListError(null);
    try {
      setInvestigations(await api.listInvestigations());
    } catch (error) {
      setListError(describeError(error));
    } finally {
      setListLoading(false);
    }
  }

  const resetPipelineState = useCallback(() => {
    if (satellitePresentationRef.current?.imageUrl) URL.revokeObjectURL(satellitePresentationRef.current.imageUrl);
    if (satellitePresentationRef.current?.groundTruthUrl) URL.revokeObjectURL(satellitePresentationRef.current.groundTruthUrl);
    satellitePresentationRef.current = null;
    setScenarios(null);
    setEvidenceAssets([]);
    setSatellite(null);
    setSatellitePresentation(null);
    setAisAsset(null);
    setEnvironmentAsset(null);
    setBackwardDrift(null);
    setForwardDrift(null);
    setAttribution(null);
    setSelectedMmsi(null);
    setBackwardError(null);
    setForwardError(null);
    setAttributionError(null);
  }, []);

  async function handleCreateInvestigation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (newTitle.trim().length < 3) {
      setCreateError("Give the investigation a title of at least 3 characters.");
      return;
    }
    setCreating(true);
    setCreateError(null);
    try {
      const created = await api.createInvestigation({ title: newTitle.trim() });
      setInvestigations((previous) => [created, ...previous]);
      setInvestigation(created);
      rememberCase(created.id);
      setNewTitle("");
      resetPipelineState();
    } catch (error) {
      setCreateError(describeError(error));
    } finally {
      setCreating(false);
    }
  }

  function rememberCase(id: string | null) {
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("case", id);
    else url.searchParams.delete("case");
    window.history.replaceState(null, "", url);
  }

  const handleSelectInvestigation = useCallback(async (id: string) => {
    const version = ++restoreVersion.current;
    setRestoring(true);
    setRestoreError(null);
    setInvestigation(null);
    resetPipelineState();
    try {
      const detail = await api.getInvestigation(id);
      if (version !== restoreVersion.current) return;
      setEvidenceAssets(detail.assets);
      const stored = detail.analyses ?? {};
      const asset = (type: "ais" | "environment") => {
        const item = detail.assets.find((entry) => entry.asset_type === type);
        return item ? { asset: item, validation: item.metadata } : null;
      };
      setScenarios(stored.release_scenarios ?? null);
      setSatellite(stored.satellite_detection ?? null);
      setAisAsset(asset("ais"));
      setEnvironmentAsset(asset("environment"));
      setBackwardDrift(stored.drift_backward ?? null);
      setForwardDrift(stored.drift_forward ?? null);
      setAttribution(stored.attribution ?? null);
      setSelectedMmsi(stored.attribution?.candidates[0]?.mmsi ?? null);
      setInvestigation(detail);
      rememberCase(id);
    } catch (error) {
      if (version !== restoreVersion.current) return;
      setRestoreError(describeError(error));
    } finally {
      if (version === restoreVersion.current) setRestoring(false);
    }
  }, [resetPipelineState]);

  useEffect(() => {
    void loadInvestigations();
    const id = new URLSearchParams(window.location.search).get("case");
    if (id) void handleSelectInvestigation(id);
    return () => { restoreVersion.current += 1; };
  }, [handleSelectInvestigation]);


  async function handleRunBackward(payload: DriftRequest) {
    setBackwardLoading(true);
    setBackwardError(null);
    try {
      setBackwardDrift(await api.driftBackward(payload));
    } catch (error) {
      setBackwardError(describeError(error));
    } finally {
      setBackwardLoading(false);
    }
  }

  async function handleRunForward(payload: DriftRequest) {
    setForwardLoading(true);
    setForwardError(null);
    try {
      setForwardDrift(await api.driftForward(payload));
    } catch (error) {
      setForwardError(describeError(error));
    } finally {
      setForwardLoading(false);
    }
  }

  async function handleRunAttribution(payload: AttributionRequest) {
    setAttributionLoading(true);
    setAttributionError(null);
    try {
      const response = await api.rankSuspects(payload);
      setAttribution(response);
      setSelectedMmsi(response.candidates[0]?.mmsi ?? null);
    } catch (error) {
      setAttributionError(describeError(error));
    } finally {
      setAttributionLoading(false);
    }
  }

  const spillCentroid = useMemo<[number, number] | null>(() => {
    if (!satellite) return null;
    const metrics = satellite.validation.geometry_metrics as { centroid?: number[] } | undefined;
    if (metrics?.centroid?.length === 2) return [metrics.centroid[1], metrics.centroid[0]];
    return computeCentroid(satellite.geojson);
  }, [satellite]);
  const satelliteObservedAt = useMemo(() => {
    const value = satellite?.validation.acquired_at;
    return typeof value === "string" && value.length > 0 ? value : null;
  }, [satellite]);
  const suggestedOrigin = useMemo(() => (backwardDrift ? extractHindcastOrigin(backwardDrift) : null), [backwardDrift]);

  const completedStages = useMemo<Set<FlowStageKey>>(() => {
    const stages = new Set<FlowStageKey>();
    if (satellite) stages.add("ingestion");
    if (satellite && satellite.geojson.features.length > 0) stages.add("mask");
    if (backwardDrift) {
      stages.add("drift");
      stages.add("origin");
    }
    if (attribution) stages.add("aisFilter");
    if (attribution && attribution.candidate_count > 0) stages.add("suspect");
    return stages;
  }, [satellite, backwardDrift, attribution]);

  const activeStage: FlowStageKey | null = backwardLoading || forwardLoading ? "drift" : attributionLoading ? "aisFilter" : null;

  async function handleReportDownload(format: "pdf" | "package") {
    if (!investigation) return;
    setReportLoading(format);
    setReportError(null);
    const payload = { investigation_id: investigation.id };
    try {
      if (format === "pdf") await api.downloadForensicPdf(payload);
      else await api.downloadForensicPackage(payload);
    } catch (error) {
      setReportError(describeError(error));
    } finally {
      setReportLoading(null);
    }
  }

  if (restoring) return <p role="status">Restoring saved investigation…</p>;

  if (!investigation) {
    return (
      <section className="investigation-gate" aria-labelledby="investigation-gate-title">
        <div className="investigation-gate__card">
          <FolderPlus size={26} aria-hidden="true" />
          <h2 id="investigation-gate-title">Open or start an investigation</h2>
          <p>Every upload, drift run, and suspect ranking below is attached to a real investigation record on the SeaScan backend.</p>

          {restoreError && <p role="alert">Could not restore investigation: {restoreError}</p>}
          {listLoading && <p className="investigation-gate__status">Loading existing investigations…</p>}
          {listError && <p className="investigation-gate__status investigation-gate__status--error">{listError}</p>}

          {!listLoading && investigations.length > 0 && (
            <label className="investigation-gate__select">
              <span>Continue an existing investigation</span>
              <select defaultValue="" onChange={(event) => event.target.value && handleSelectInvestigation(event.target.value)}>
                <option value="" disabled>
                  Select an investigation…
                </option>
                {investigations.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title}
                  </option>
                ))}
              </select>
            </label>
          )}

          {canManageEvidence ? <form onSubmit={(event) => void handleCreateInvestigation(event)} className="investigation-gate__form">
            <label>
              <span>New investigation title</span>
              <input
                type="text"
                minLength={3}
                maxLength={160}
                placeholder="Arabian Sea slick — 2026-09-13"
                value={newTitle}
                onChange={(event) => setNewTitle(event.target.value)}
              />
            </label>
            <button type="submit" disabled={creating}>
              {creating ? "Creating…" : "Start investigation"}
            </button>
          </form> : <p className="investigation-gate__status">Analysts can open and analyse existing investigations. An investigator or administrator creates new cases and uploads evidence.</p>}
          {createError && <p className="investigation-gate__status investigation-gate__status--error">{createError}</p>}
        </div>
      </section>
    );
  }

  return (
    <section className="forensics-workspace" aria-label="Maritime forensics dashboard">
      <header className="forensics-workspace__header">
        <div>
          <p className="eyebrow">Active investigation</p>
          <h2>{investigation.title}</h2>
        </div>
        <div className="forensics-workspace__header-actions">
          <button type="button" className="secondary-button" onClick={() => void handleReportDownload("pdf")} disabled={scenarioBusy || workflowBusy || reportLoading !== null}>
            <Download size={16} /> {reportLoading === "pdf" ? "Building PDF…" : "Export PDF"}
          </button>
          <button type="button" className="secondary-button" onClick={() => void handleReportDownload("package")} disabled={scenarioBusy || workflowBusy || reportLoading !== null}>
            <FileArchive size={16} /> {reportLoading === "package" ? "Packaging…" : "Evidence package"}
          </button>
          <button type="button" className="secondary-button" disabled={scenarioBusy || workflowBusy || backwardLoading || forwardLoading || attributionLoading || reportLoading !== null} onClick={() => { rememberCase(null); setInvestigation(null); resetPipelineState(); void loadInvestigations(); }}>
            Switch investigation
          </button>
          {canManageEvidence && <button type="button" className="primary-button" disabled={scenarioBusy || workflowBusy} onClick={() => setUploadOpen(true)}>
            <UploadCloud size={16} /> Upload evidence
          </button>}
        </div>
      </header>

      {reportError && <p className="report-export-error" role="alert">Report export failed: {reportError}</p>}

      <div className="asset-chip-row" role="list">
        <span role="listitem" className={`asset-chip ${satellite ? "asset-chip--ready" : ""}`}>
          <Satellite size={14} /> Satellite {satellite ? `· ${satellite.geojson.features.length} segment(s)` : "· not uploaded"}
        </span>
        <span role="listitem" className={`asset-chip ${environmentAsset ? "asset-chip--ready" : ""}`}>
          <Waves size={14} /> Environment {environmentAsset ? "· ready" : "· not uploaded"}
        </span>
        <span role="listitem" className={`asset-chip ${aisAsset ? "asset-chip--ready" : ""}`}>
          <ShieldCheck size={14} /> AIS {aisAsset ? "· ready" : "· not uploaded"}
        </span>
      </div>

      {((backwardDrift && !backwardDrift.parameters) || (forwardDrift && !forwardDrift.parameters) || (attribution && !attribution.parameters)) && (
        <p role="note">This older case did not record every analysis setting. Saved results are restored; unrecorded settings use defaults or the hindcast suggestion. Review them before running again.</p>
      )}

      <EvidenceProvenancePanel assets={evidenceAssets} />

      <AnalysisWorkflow
        key={`${investigation.id}:${satellite?.asset.id}:${environmentAsset?.asset.id}:${aisAsset?.asset.id}`}
        satellite={satellite} environment={environmentAsset} ais={aisAsset} centroid={spillCentroid}
        disabled={scenarioBusy || backwardLoading || forwardLoading || attributionLoading || reportLoading !== null || uploadOpen}
        onBusy={setWorkflowBusy} onBackward={setBackwardDrift} onForward={setForwardDrift}
        onAttribution={(result) => { setAttribution(result); setSelectedMmsi(result.candidates[0]?.mmsi ?? null); }}
      />

      <ReleaseScenarios key={investigation.id} environmentId={environmentAsset?.asset.id} aisId={aisAsset?.asset.id}
        centroid={spillCentroid} result={scenarios} onResult={setScenarios} onBusy={setScenarioBusy}
        disabled={workflowBusy || backwardLoading || forwardLoading || attributionLoading || reportLoading !== null || uploadOpen} />

      <IntelligenceFlowGraph completedStages={completedStages} activeStage={activeStage} />

      <fieldset className="controls-row workflow-fields" disabled={scenarioBusy || workflowBusy}>
        <DriftControls
          key={investigation.id}
          savedBackward={backwardDrift}
          savedForward={forwardDrift}
          environmentAsset={environmentAsset}
          spillCentroid={spillCentroid}
          satelliteObservedAt={satelliteObservedAt}
          onRunBackward={(payload) => void handleRunBackward(payload)}
          onRunForward={(payload) => void handleRunForward(payload)}
          backwardLoading={backwardLoading}
          forwardLoading={forwardLoading}
          backwardError={backwardError}
          forwardError={forwardError}
          backwardResult={backwardDrift}
          forwardResult={forwardDrift}
        />
        <AttributionControls
          key={investigation.id}
          savedParameters={attribution?.parameters}
          aisAsset={aisAsset}
          suggestedOrigin={suggestedOrigin}
          onRun={(payload) => void handleRunAttribution(payload)}
          loading={attributionLoading}
          error={attributionError}
        />
      </fieldset>

      <div className="dashboard-grid">
        <MaritimeMap
          satellite={satellite ? {
            geojson: satellite.geojson,
            bounds: satellitePresentation?.bounds ?? null,
            imageUrl: satellitePresentation?.imageUrl ?? null,
            groundTruthUrl: satellitePresentation?.groundTruthUrl ?? null,
            centroid: spillCentroid,
          } : null}
          backwardDrift={backwardDrift}
          forwardDrift={forwardDrift}
          candidates={attribution?.candidates ?? []}
          selectedMmsi={selectedMmsi}
          onSelectVessel={setSelectedMmsi}
        />
        <SuspectVesselPanel
          attribution={attribution}
          isLoading={attributionLoading}
          error={attributionError}
          selectedMmsi={selectedMmsi}
          onSelectVessel={setSelectedMmsi}
        />
      </div>

      <ForensicStory
        investigation={investigation}
        satellite={satellite}
        environmentAsset={environmentAsset?.asset ?? null}
        aisAsset={aisAsset?.asset ?? null}
        backwardDrift={backwardDrift}
        forwardDrift={forwardDrift}
        candidates={attribution?.candidates ?? []}
      />

      <UploadModal
        investigationId={investigation.id}
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        acceptedFormats={acceptedFormats}
        onSatelliteUploaded={(response, presentation) => {
          if (satellitePresentationRef.current?.imageUrl) URL.revokeObjectURL(satellitePresentationRef.current.imageUrl);
          if (satellitePresentationRef.current?.groundTruthUrl) URL.revokeObjectURL(satellitePresentationRef.current.groundTruthUrl);
          satellitePresentationRef.current = presentation;
          setSatellite(response);
          setSatellitePresentation(presentation);
          setEvidenceAssets((assets) => [response.asset, ...assets]);
        }}
        onAisUploaded={(response) => { setAisAsset(response); setEvidenceAssets((assets) => [response.asset, ...assets]); }}
        onEnvironmentUploaded={(response) => { setEnvironmentAsset(response); setEvidenceAssets((assets) => [response.asset, ...assets]); }}
      />
    </section>
  );
}
