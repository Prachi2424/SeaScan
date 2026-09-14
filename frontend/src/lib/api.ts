import type {
  AttributionRequest,
  AttributionResponse,
  DriftRequest,
  DriftResponse,
  ForensicReportRequest,
  HealthResponse,
  IngestionResponse,
  InvestigationCreate,
  InvestigationDetail,
  InvestigationSummary,
  SatelliteDetectionResponse,
  SystemConfigResponse,
} from "../types/api";

const baseUrl = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.clone().json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail
        .map((item) => (typeof item === "object" && item && "msg" in item ? String((item as { msg: unknown }).msg) : JSON.stringify(item)))
        .join("; ");
    }
  } catch {
    /* response body was not JSON — fall through to the generic message below */
  }
  return `Request failed with status ${response.status}`;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: { Accept: "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorDetail(response));
  }
  return response.json() as Promise<T>;
}

async function requestDownload(path: string, payload: ForensicReportRequest): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers: { Accept: path.endsWith(".pdf") ? "application/pdf" : "application/zip", "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new ApiError(response.status, await parseErrorDetail(response));
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] ?? (path.endsWith(".pdf") ? "seascan-forensic-report.pdf" : "seascan-forensic-package.zip");
  return { blob: await response.blob(), filename };
}

function saveDownload(download: { blob: Blob; filename: string }): void {
  const url = URL.createObjectURL(download.blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = download.filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function toJsonBody(payload: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  };
}

// ---------------------------------------------------------------------------
// System
// ---------------------------------------------------------------------------

function health(): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/api/health");
}

function systemConfig(): Promise<SystemConfigResponse> {
  return requestJson<SystemConfigResponse>("/api/system/config");
}

// ---------------------------------------------------------------------------
// Investigations
// ---------------------------------------------------------------------------

function createInvestigation(payload: InvestigationCreate): Promise<InvestigationSummary> {
  return requestJson<InvestigationSummary>("/api/investigations", toJsonBody(payload));
}

function listInvestigations(): Promise<InvestigationSummary[]> {
  return requestJson<InvestigationSummary[]>("/api/investigations");
}

function getInvestigation(investigationId: string): Promise<InvestigationDetail> {
  return requestJson<InvestigationDetail>(`/api/investigations/${encodeURIComponent(investigationId)}`);
}

// ---------------------------------------------------------------------------
// Ingestion — real file uploads only, no mock endpoints
// ---------------------------------------------------------------------------

function uploadAis(investigationId: string, file: File): Promise<IngestionResponse> {
  const form = new FormData();
  form.append("investigation_id", investigationId);
  form.append("file", file);
  return requestJson<IngestionResponse>("/api/ais/upload", { method: "POST", body: form });
}

function uploadEnvironment(investigationId: string, file: File): Promise<IngestionResponse> {
  const form = new FormData();
  form.append("investigation_id", investigationId);
  form.append("file", file);
  return requestJson<IngestionResponse>("/api/environment/upload", { method: "POST", body: form });
}

interface SatelliteUploadOptions {
  threshold?: number;
  bounds?: { west: number; south: number; east: number; north: number };
}

function uploadSatellite(
  investigationId: string,
  file: File,
  options: SatelliteUploadOptions = {},
): Promise<SatelliteDetectionResponse> {
  const form = new FormData();
  form.append("investigation_id", investigationId);
  form.append("file", file);
  form.append("threshold", String(options.threshold ?? 0.5));
  if (options.bounds) {
    form.append("west", String(options.bounds.west));
    form.append("south", String(options.bounds.south));
    form.append("east", String(options.bounds.east));
    form.append("north", String(options.bounds.north));
  }
  return requestJson<SatelliteDetectionResponse>("/api/satellite/upload", { method: "POST", body: form });
}

// ---------------------------------------------------------------------------
// Forensics — drift hindcast / forecast
// ---------------------------------------------------------------------------

function driftBackward(payload: DriftRequest): Promise<DriftResponse> {
  return requestJson<DriftResponse>("/api/drift/backward", toJsonBody(payload));
}

function driftForward(payload: DriftRequest): Promise<DriftResponse> {
  return requestJson<DriftResponse>("/api/drift/forward", toJsonBody(payload));
}

// ---------------------------------------------------------------------------
// Forensics — explainable AIS attribution
// ---------------------------------------------------------------------------

function rankSuspects(payload: AttributionRequest): Promise<AttributionResponse> {
  return requestJson<AttributionResponse>("/api/attribution/rank", toJsonBody(payload));
}

async function downloadForensicPdf(payload: ForensicReportRequest): Promise<void> {
  saveDownload(await requestDownload("/api/reports/forensic.pdf", payload));
}

async function downloadForensicPackage(payload: ForensicReportRequest): Promise<void> {
  saveDownload(await requestDownload("/api/reports/package.zip", payload));
}

export const api = {
  health,
  systemConfig,
  createInvestigation,
  listInvestigations,
  getInvestigation,
  uploadAis,
  uploadEnvironment,
  uploadSatellite,
  driftBackward,
  driftForward,
  rankSuspects,
  downloadForensicPdf,
  downloadForensicPackage,
};
