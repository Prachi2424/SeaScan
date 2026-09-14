import { useEffect, useId, useRef, useState } from "react";
import mermaid from "mermaid";

export type FlowStageKey = "ingestion" | "mask" | "drift" | "origin" | "aisFilter" | "suspect";

interface IntelligenceFlowGraphProps {
  completedStages: ReadonlySet<FlowStageKey>;
  activeStage?: FlowStageKey | null;
}

const STAGE_ORDER: { key: FlowStageKey; id: string; label: string }[] = [
  { key: "ingestion", id: "ingestion", label: "Satellite Ingestion" },
  { key: "mask", id: "mask", label: "Segmentation Mask" },
  { key: "drift", id: "drift", label: "Environmental Vector Drift" },
  { key: "origin", id: "origin", label: "Origin Window" },
  { key: "aisFilter", id: "aisFilter", label: "AIS Spatial-Temporal Filter" },
  { key: "suspect", id: "suspect", label: "Scored Suspect" },
];

let mermaidInitialized = false;
function ensureMermaidInitialized() {
  if (mermaidInitialized) return;
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    theme: "base",
    themeVariables: {
      darkMode: true,
      background: "#061525",
      primaryColor: "#0d3346",
      primaryTextColor: "#e6f4f7",
      primaryBorderColor: "#3bbccc",
      lineColor: "#3bbccc",
      secondaryColor: "#0a2434",
      tertiaryColor: "#0a2434",
      fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
      fontSize: "14px",
    },
    flowchart: { curve: "basis", htmlLabels: false, padding: 12 },
  });
  mermaidInitialized = true;
}

function buildDefinition(completedStages: ReadonlySet<FlowStageKey>, activeStage: FlowStageKey | null | undefined): string {
  const nodeLines = STAGE_ORDER.map((stage) => `${stage.id}["${stage.label}"]`);
  const edgeLines = ["ingestion --> mask", "mask --> drift", "drift --> origin", "origin --> aisFilter", "aisFilter --> suspect"];
  const classLines = STAGE_ORDER.map((stage) => {
    if (completedStages.has(stage.key)) return `class ${stage.id} done;`;
    if (stage.key === activeStage) return `class ${stage.id} active;`;
    return `class ${stage.id} pending;`;
  });
  return [
    "graph LR",
    ...nodeLines,
    ...edgeLines,
    "classDef done fill:#134f3f,stroke:#3ee08c,stroke-width:2px,color:#e9fff2;",
    "classDef active fill:#0d3f57,stroke:#f4c969,stroke-width:2px,color:#fff6df;",
    "classDef pending fill:#0a2434,stroke:#2b5568,stroke-width:1px,color:#7fa0ae;",
    ...classLines,
  ].join("\n");
}

export function IntelligenceFlowGraph({ completedStages, activeStage = null }: IntelligenceFlowGraphProps) {
  const rawId = useId().replace(/[^a-zA-Z0-9]/g, "");
  const [svgMarkup, setSvgMarkup] = useState<string>("");
  const [renderError, setRenderError] = useState<string | null>(null);
  const renderToken = useRef(0);

  useEffect(() => {
    ensureMermaidInitialized();
    const token = ++renderToken.current;
    const definition = buildDefinition(completedStages, activeStage);

    mermaid
      .render(`flow-${rawId}`, definition)
      .then(({ svg }) => {
        if (renderToken.current === token) {
          setSvgMarkup(svg);
          setRenderError(null);
        }
      })
      .catch((error: unknown) => {
        if (renderToken.current === token) {
          setRenderError(error instanceof Error ? error.message : "Unable to render the evidence chain graph.");
        }
      });
  }, [completedStages, activeStage, rawId]);

  const completedCount = STAGE_ORDER.filter((stage) => completedStages.has(stage.key)).length;

  return (
    <section className="flow-graph" aria-label="Multi-source intelligence evidence chain">
      <header className="flow-graph__header">
        <h2>Evidence chain</h2>
        <span>{completedCount} / {STAGE_ORDER.length} stages complete</span>
      </header>
      {renderError ? (
        <p className="flow-graph__error">{renderError}</p>
      ) : (
        <div className="flow-graph__canvas" role="img" dangerouslySetInnerHTML={{ __html: svgMarkup }} />
      )}
    </section>
  );
}
