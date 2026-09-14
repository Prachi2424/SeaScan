import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Compass,
  Database,
  Radar,
  RefreshCw,
  Route,
  Satellite,
  ScanLine,
  Server,
  Ship,
  ShipWheel,
  Waves,
} from "lucide-react";

import { StatusDot } from "./components/StatusDot";
import { ForensicsWorkspace } from "./components/ForensicsWorkspace";
import { api } from "./lib/api";
import type { SystemConfigResponse } from "./types/api";

type ConnectionStatus = "online" | "offline" | "checking";
type ViewKey = "overview" | "workspace";

export default function App() {
  const [status, setStatus] = useState<ConnectionStatus>("checking");
  const [config, setConfig] = useState<SystemConfigResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<ViewKey>("overview");

  const refreshConnection = useCallback(async () => {
    setStatus("checking");
    setError(null);
    try {
      const [health, systemConfig] = await Promise.all([api.health(), api.systemConfig()]);
      if (health.status !== "ok") throw new Error("The SeaScan API did not report a healthy status.");
      setConfig(systemConfig);
      setStatus("online");
    } catch (caughtError) {
      setStatus("offline");
      setConfig(null);
      setError(caughtError instanceof Error ? caughtError.message : "Unable to contact the SeaScan API.");
    }
  }, []);

  useEffect(() => {
    void refreshConnection();
  }, [refreshConnection]);

  useEffect(() => {
    if (status !== "online" && view === "workspace") setView("overview");
  }, [status, view]);

  const navigation: { key: ViewKey; label: string; icon: typeof Radar; disabled: boolean }[] = [
    { key: "overview", label: "Overview", icon: Compass, disabled: false },
    { key: "workspace", label: "Investigation Workspace", icon: Radar, disabled: status !== "online" },
  ];

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand"><ShipWheel size={27} aria-hidden="true" /><span>Sea<span>Scan</span></span></div>
        <p className="eyebrow">Maritime intelligence</p>
        <nav aria-label="Platform sections">
          {navigation.map(({ key, label, icon: Icon, disabled }) => (
            <button
              className={`nav-item ${view === key ? "nav-item--current" : ""}`}
              key={key}
              type="button"
              disabled={disabled}
              onClick={() => setView(key)}
            >
              <Icon size={18} aria-hidden="true" /> {label}
              {disabled && <small>API offline</small>}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <p>REAL-DATA MODE</p>
          <span><StatusDot status={status} /> API {status}</span>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">{view === "workspace" ? "Case workspace" : "Service status"}</p>
            <h1>{view === "workspace" ? "Maritime forensics dashboard" : "SeaScan platform overview"}</h1>
          </div>
          <button className="refresh-button" type="button" onClick={() => void refreshConnection()} disabled={status === "checking"}>
            <RefreshCw size={16} className={status === "checking" ? "spin" : ""} /> Refresh connection
          </button>
        </header>

        {view === "overview" ? (
          <OverviewView status={status} config={config} error={error} onOpenWorkspace={() => setView("workspace")} />
        ) : (
          config && (
            <ForensicsWorkspace
              acceptedFormats={{
                satellite: config.accepted_satellite_formats,
                ais: config.accepted_ais_formats,
                environment: config.accepted_environmental_formats,
              }}
            />
          )
        )}
      </section>
    </main>
  );
}

const stageIcons = [Satellite, ScanLine, Waves, Route, Ship, CheckCircle2];

function OverviewView({
  status,
  config,
  error,
  onOpenWorkspace,
}: {
  status: ConnectionStatus;
  config: SystemConfigResponse | null;
  error: string | null;
  onOpenWorkspace: () => void;
}) {
  return (
    <>
      <section className="stage-card" aria-labelledby="phase-title">
        <div className="stage-card__content">
          <div className="stage-card__badge"><Radar size={14} aria-hidden="true" /> Mission-ready intelligence</div>
          <h2 id="phase-title">Trace marine pollution<br />back to its source.</h2>
          <p>Fuse satellite detections, ocean drift, and AIS vessel history into one evidence-led investigation.</p>
          <div className="stage-card__actions">
            <button className="primary-button primary-button--large" type="button" onClick={onOpenWorkspace} disabled={status !== "online"}>
              Open investigation workspace <ArrowRight size={17} aria-hidden="true" />
            </button>
            <span><StatusDot status={status} /> {status === "online" ? "All systems operational" : status === "checking" ? "Connecting to API" : "API connection required"}</span>
          </div>
        </div>
        <div className="stage-card__visual" aria-hidden="true">
          <div className="radar-orbit radar-orbit--outer" />
          <div className="radar-orbit radar-orbit--inner" />
          <div className="radar-sweep" />
          <div className="radar-core"><Ship size={28} /></div>
          <span className="radar-point radar-point--one" />
          <span className="radar-point radar-point--two" />
          <span className="radar-point radar-point--three" />
        </div>
      </section>

      <section className="overview-stats" aria-label="Platform status">
        <article><Server size={18} /><div><strong>{status === "online" ? "Online" : status === "checking" ? "Checking" : "Offline"}</strong><span>API service</span></div></article>
        <article><Activity size={18} /><div><strong>{config?.pipeline_stages.length ?? "—"}</strong><span>Analysis stages</span></div></article>
        <article><Database size={18} /><div><strong>{config ? `${config.max_upload_size_mb} MB` : "—"}</strong><span>Evidence upload</span></div></article>
      </section>

      {error && <p className="connection-error" role="alert">{error}</p>}

      <section className="capabilities-section" aria-labelledby="capabilities-title">
        <div className="section-heading">
          <div><p className="eyebrow">End-to-end workflow</p><h2 id="capabilities-title">From detection to attribution</h2></div>
          <p>Every stage stays grounded in the evidence you upload.</p>
        </div>
        <div className="capability-grid" aria-label="Backend capabilities">
          {config?.pipeline_stages.map((stage, index) => {
            const Icon = stageIcons[index] ?? Activity;
            return (
              <article className="capability-card" key={stage}>
                <div className="capability-card__top"><span>{String(index + 1).padStart(2, "0")}</span><Icon size={19} aria-hidden="true" /></div>
                <h3>{stage.replace(/_/g, " ")}</h3>
                <p>{getStageDescription(stage)}</p>
              </article>
            );
          })}
        </div>
      </section>

      {config && (
        <section className="config-panel" aria-labelledby="config-title">
          <div><p className="eyebrow">Evidence compatibility</p><h2 id="config-title">Validated real-data inputs</h2></div>
          <div className="format-groups">
            <FormatGroup label="Satellite" formats={config.accepted_satellite_formats} />
            <FormatGroup label="AIS" formats={config.accepted_ais_formats} />
            <FormatGroup label="Environment" formats={config.accepted_environmental_formats} />
          </div>
        </section>
      )}
    </>
  );
}

function getStageDescription(stage: string): string {
  const descriptions: Record<string, string> = {
    satellite_ingestion: "Load and validate geospatial raster evidence.",
    spill_segmentation: "Isolate suspected slicks from satellite scenes.",
    environmental_fusion: "Join wind and current observations to the case.",
    drift_hindcast: "Reconstruct the likely movement of the slick.",
    ais_reconstruction: "Review vessel tracks near the estimated origin.",
    explainable_vessel_ranking: "Rank candidates with transparent evidence scores.",
  };
  return descriptions[stage] ?? "Verified analysis stage available for this investigation.";
}

function FormatGroup({ label, formats }: { label: string; formats: string[] }) {
  return <div><h3>{label}</h3><p>{formats.join(" · ")}</p></div>;
}
