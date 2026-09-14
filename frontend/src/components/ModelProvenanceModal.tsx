import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Database, RefreshCw, ShieldCheck, X } from "lucide-react";
import "./ModelProvenanceModal.css";

type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
interface ModelInfo {
  architecture: string;
  architecture_parameters: Record<string, number>;
  weights_path: string;
  weights_sha256: string;
  metadata_path: string | null;
  metadata_source: string;
  input_shape: [number, number, number] | null;
  trained_at: string;
  dataset_sample_count: number;
  dataset_provenance: Record<string, JsonValue> | null;
  metrics: {
    weights_sha256: string;
    checkpoint_epoch: number;
    training_epochs: number | null;
    dice_score: number;
    iou: number | null;
    metric_source: string;
  };
  missing_fields: string[];
}
type LoadState = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; model: ModelInfo };
const baseUrl = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

async function fetchModel(signal: AbortSignal): Promise<ModelInfo> {
  const response = await fetch(`${baseUrl}/api/model/info`, {
    signal, headers: { Accept: "application/json" }, cache: "no-store",
  });
  if (!response.ok) {
    let message = `Model information request failed (${response.status}).`;
    try {
      const body: unknown = await response.json();
      if (typeof body === "object" && body !== null && "detail" in body && typeof body.detail === "string") message = body.detail;
    } catch {
      message = `Model information request failed (${response.status}).`;
    }
    throw new Error(message);
  }
  return response.json() as Promise<ModelInfo>;
}
function formatScore(value: number | null): string {
  return value === null ? "Not recorded" : `${(value * 100).toFixed(2)}%`;
}
function Field({ label, value }: { label: string; value: string | number | null }) {
  return <div className="model-provenance__field"><dt>{label}</dt><dd>{value ?? "Not recorded"}</dd></div>;
}

export function ModelProvenanceModal({ onClose }: { onClose: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<LoadState>({ status: "loading" });
  useEffect(() => {
    const dialog = dialogRef.current;
    const previouslyFocused = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    dialog?.showModal();
    document.body.style.overflow = "hidden";
    return () => {
      dialog?.close();
      document.body.style.overflow = previousOverflow;
      if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus();
    };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    let timedOut = false;
    const timeout = window.setTimeout(() => { timedOut = true; controller.abort(); }, 60_000);
    void fetchModel(controller.signal).then((model) => {
      if (active) setState({ status: "ready", model });
    }).catch((error: unknown) => {
      if (!active) return;
      setState({ status: "error", message: timedOut ? "Model inspection timed out. Please retry." : error instanceof Error ? error.message : "Unable to retrieve model information." });
    }).finally(() => window.clearTimeout(timeout));
    return () => { active = false; controller.abort(); window.clearTimeout(timeout); };
  }, [attempt]);
  function retry() { setState({ status: "loading" }); setAttempt((value) => value + 1); }
  return createPortal(
    <dialog ref={dialogRef} className="model-provenance" aria-labelledby={titleId} aria-describedby={descriptionId}
      onCancel={(event) => { event.preventDefault(); onClose(); }}>
      <header className="model-provenance__header">
        <div>
          <p className="model-provenance__eyebrow"><ShieldCheck size={16} aria-hidden="true" /> Model provenance</p>
          <h2 id={titleId}>Segmentation model evidence</h2>
          <p id={descriptionId}>Checkpoint identity, architecture, and recorded training results.</p>
        </div>
        <button type="button" className="model-provenance__close" aria-label="Close model provenance" onClick={onClose} autoFocus><X size={20} aria-hidden="true" /></button>
      </header>
      <div className="model-provenance__body">
        {state.status === "loading" && <p role="status">Inspecting the configured checkpoint…</p>}
        {state.status === "error" && <div role="alert" className="model-provenance__notice">
          <h3>Model information unavailable</h3><p>{state.message}</p>
          <button type="button" onClick={retry}><RefreshCw size={16} aria-hidden="true" /> Retry</button>
        </div>}
        {state.status === "ready" && <>
          <section aria-label="Recorded validation performance">
            <div className="model-provenance__metrics">
              <article><span>Validation Dice</span><strong>{formatScore(state.model.metrics.dice_score)}</strong></article>
              <article><span>Validation IoU</span><strong>{formatScore(state.model.metrics.iou)}</strong></article>
            </div>
            <p className="model-provenance__muted">Recorded training results; these are not a new independent evaluation or a measure of vessel attribution accuracy.</p>
          </section>
          {state.model.missing_fields.length > 0 && <p className="model-provenance__notice">This checkpoint does not record: {state.model.missing_fields.map((field) => field.replace(/_/g, " ")).join(", ")}. No values have been estimated.</p>}
          <section aria-label="Architecture and training"><h3>Architecture and training</h3>
            <dl className="model-provenance__grid">
              <Field label="Architecture" value={state.model.architecture} />
              <Field label="Training input shape (C × H × W)" value={state.model.input_shape?.join(" × ") ?? null} />
              <Field label="Checkpoint epoch" value={state.model.metrics.checkpoint_epoch} />
              <Field label="Total training epochs" value={state.model.metrics.training_epochs} />
              <Field label="Recorded training time" value={state.model.trained_at} />
              <Field label="Dataset samples" value={state.model.dataset_sample_count} />
              {Object.entries(state.model.architecture_parameters).map(([name, value]) => <Field key={name} label={name.replace(/_/g, " ")} value={value.toLocaleString()} />)}
            </dl>
          </section>
          <section aria-label="Checkpoint identity"><h3>Checkpoint identity</h3><dl>
            <Field label="Weights path" value={state.model.weights_path} />
            <Field label="SHA-256" value={state.model.weights_sha256} />
            <Field label="Metadata file" value={state.model.metadata_path} />
            <Field label="Metadata source" value={state.model.metadata_source} />
          </dl><p className="model-provenance__muted">The checksum identifies the inspected weights and binds any accompanying metadata file to them. It does not independently verify the training claims.</p></section>
          <section aria-label="Training dataset provenance"><h3><Database size={17} aria-hidden="true" /> Dataset provenance</h3>
            {state.model.dataset_provenance === null ? <p className="model-provenance__muted">Not recorded.</p> : <pre>{JSON.stringify(state.model.dataset_provenance, null, 2)}</pre>}
          </section>
        </>}
      </div>
    </dialog>, document.body,
  );
}
export function ModelProvenanceControl() {
  const [open, setOpen] = useState(false);
  return <>
    <button type="button" className="model-provenance-launcher" aria-haspopup="dialog" onClick={() => setOpen(true)}><ShieldCheck size={18} aria-hidden="true" /> Model provenance</button>
    {open && <ModelProvenanceModal onClose={() => setOpen(false)} />}
  </>;
}
