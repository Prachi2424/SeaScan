import type { EvidenceAsset, EvidenceProvenance } from "../types/api";

const display = (value: unknown): string => value === null || value === undefined || value === "" ? "Not recorded" : typeof value === "object" ? JSON.stringify(value) : String(value);

export function EvidenceProvenancePanel({ assets }: { assets: EvidenceAsset[] }) {
  return <section className="evidence-provenance" aria-label="Evidence provenance">
    <h2>Evidence provenance</h2>
    <p>Source details and real/synthetic labels are uploader declarations. File identity and upload time are recorded by SeaScan. Hashes identify files; they do not verify authenticity.</p>
    {assets.length === 0 && <p>No evidence uploaded.</p>}
    {assets.map((asset) => {
      const p = (asset.metadata.provenance ?? {}) as Partial<EvidenceProvenance>;
      const metrics = (asset.metadata.geometry_metrics ?? {}) as Record<string, unknown>;
      const cleanup = (asset.metadata.cleanup ?? {}) as Record<string, unknown>;
      const model = asset.metadata.model as { architecture?: string; weights_sha256?: string } | undefined;
      const kind = p.evidence_kind === "synthetic" ? "Synthetic / demonstration" : p.evidence_kind === "real" ? "Real observations (declared)" : "Not recorded";
      const rows: [string, unknown][] = [
        ...(asset.asset_type === "satellite" ? [
          ["Minimum component size (pixels; 0 = off)", cleanup.min_component_pixels],
          ["Components removed", cleanup.removed_components], ["Pixels removed", cleanup.removed_pixels],
          ["Spill area (km²)", metrics.area_km2], ["Boundary length (km)", metrics.perimeter_km],
          ["Centroid (longitude, latitude)", Array.isArray(metrics.centroid) ? metrics.centroid.join(", ") : null],
          ["Major-axis orientation (degrees from local north)", metrics.orientation_degrees ?? "Undefined or not recorded"],
          ["Measurement method", metrics.measurement_method],
        ] as [string, unknown][] : []),
        ["Source organization", p.source_organization], ["Source reference", p.source_reference],
        ["Dataset / version", p.dataset_version], ["Acquisition time (UTC)", p.acquired_at],
        ["Uploaded at", asset.created_at], ["Original filename", asset.original_filename],
        ["File size (bytes)", asset.byte_size], ["SHA-256", asset.sha256],
        ["CRS read from file / ingestion", asset.metadata.coordinate_reference], ["CRS (declared)", p.declared_crs],
        ["Processing before upload (declared)", p.prior_processing], ["SeaScan processing", asset.metadata.processing_steps],
        ["Model architecture", model?.architecture], ["Model identity (weights SHA-256)", model?.weights_sha256],
        ["Added by (self-reported)", p.added_by],
      ];
      return <details key={asset.id}>
        <summary>{asset.asset_type.toUpperCase()} · {asset.original_filename} <strong className={`provenance-kind provenance-kind--${p.evidence_kind ?? "unknown"}`}>{kind}</strong></summary>
        <dl>{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{display(value)}</dd></div>)}</dl>
      </details>;
    })}
  </section>;
}
