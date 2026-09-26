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
  LogOut,
  UsersRound,
  Waves,
} from "lucide-react";

import { StatusDot } from "./components/StatusDot";
import { ForensicsWorkspace } from "./components/ForensicsWorkspace";
import { AuthScreen } from "./components/AuthScreen";
import { AdminPanel } from "./components/AdminPanel";
import { ModelProvenanceControl } from "./components/ModelProvenanceModal";
import { api, getAuthToken, setAuthToken } from "./lib/api";
import type { AuthUser, SystemConfigResponse } from "./types/api";

type ConnectionStatus = "online" | "offline" | "checking";
type ViewKey = "overview" | "workspace" | "administration";

export default function App() {
  const [status, setStatus] = useState<ConnectionStatus>("checking");
  const [config, setConfig] = useState<SystemConfigResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
  const [authChecking, setAuthChecking] = useState(true);
  const [view, setView] = useState<ViewKey>(() => new URLSearchParams(window.location.search).has("case") ? "workspace" : "overview");

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
    const token = getAuthToken();
    if (!token) { setAuthChecking(false); return; }
    void api.me().then(setCurrentUser).catch(() => setAuthToken(null)).finally(() => setAuthChecking(false));
  }, [refreshConnection]);

  useEffect(() => {
    if (status === "offline" && view === "workspace") setView("overview");
  }, [status, view]);

  const navigation: { key: ViewKey; label: string; icon: typeof Radar; disabled: boolean }[] = [
    { key: "overview", label: "Overview", icon: Compass, disabled: false },
    { key: "workspace", label: "Investigation Workspace", icon: Radar, disabled: status !== "online" },
    ...(currentUser?.role === "administrator" ? [{ key: "administration" as const, label: "User Administration", icon: UsersRound, disabled: status !== "online" }] : []),
  ];

  async function signOut() {
    try { await api.logout(); } finally {
      setAuthToken(null);
      setCurrentUser(null);
      setView("overview");
    }
  }

  if (authChecking || status === "checking") return <div className="auth-loading"><ShipWheel size={32} /><span>Establishing secure SeaScan session…</span></div>;
  if (status === "online" && !currentUser) return <AuthScreen onAuthenticated={setCurrentUser} developmentMode={config?.environment === "development"} />;
  const pageTitle = view === "workspace" ? "Maritime forensics dashboard" : view === "administration" ? "Identity and access control" : "SeaScan platform overview";
  const pageEyebrow = view === "workspace" ? "Case workspace" : view === "administration" ? "Administration" : "Service status";

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
          {currentUser && <div className="sidebar-user"><div>{currentUser.display_name.split(/\s+/).map((part) => part[0]).slice(0, 2).join("").toUpperCase()}</div><span><strong>{currentUser.display_name}</strong><small>{currentUser.role}</small></span></div>}
          <p>EVIDENCE MODE</p>
          <span><StatusDot status={status} /> API {status}</span>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">{pageEyebrow}</p>
            <h1>{pageTitle}</h1>
          </div>
          <div className="topbar__actions"><button className="refresh-button" type="button" onClick={() => void refreshConnection()}>
              <RefreshCw size={16} /> Refresh connection
            </button>
            {currentUser && <button className="logout-button" type="button" onClick={() => void signOut()}><LogOut size={16} /> Sign out</button>}
          </div>
        </header>

        {view === "overview" ? (
          <OverviewView status={status} config={config} error={error} onOpenWorkspace={() => setView("workspace")} />
        ) : view === "administration" && currentUser?.role === "administrator" ? (
          <AdminPanel currentUser={currentUser} />
        ) : (
          config && (
            <ForensicsWorkspace
              userRole={currentUser?.role ?? "analyst"}
              acceptedFormats={{
                satellite: config.accepted_satellite_formats,
                ais: config.accepted_ais_formats,
                environment: config.accepted_environmental_formats,
              }}
            />
          )
        )}
      </section>
      <ModelProvenanceControl />
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
          <div><p className="eyebrow">Evidence compatibility</p><h2 id="config-title">Supported evidence formats</h2></div>
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
