import type { AttributionRequest, AttributionResponse, DriftRequest, DriftResponse } from "../types/api";

export interface WorkflowApi {
  driftBackward: (request: DriftRequest) => Promise<DriftResponse>;
  driftForward: (request: DriftRequest) => Promise<DriftResponse>;
  rankSuspects: (request: AttributionRequest) => Promise<AttributionResponse>;
}

// Each endpoint saves its successful result before the next stage starts.
export async function runWorkflow(
  api: WorkflowApi,
  drift: DriftRequest,
  forecastHours: number,
  ranking: Omit<AttributionRequest, "origin_latitude" | "origin_longitude" | "estimated_origin_at" | "use_hindcast_region">,
  progress: (stage: "hindcast" | "forecast" | "ranking") => void,
  results: { backward: (result: DriftResponse) => void; forward: (result: DriftResponse) => void; attribution: (result: AttributionResponse) => void },
) {
  progress("hindcast");
  const backward = await api.driftBackward(drift);
  results.backward(backward);
  const origin = backward.trajectory.features.at(-1);
  if (origin?.geometry.type !== "Point" || !origin.properties?.timestamp) {
    throw new Error("Hindcast returned no usable origin. Review the drift evidence before ranking.");
  }
  const [longitude, latitude] = origin.geometry.coordinates;
  if (![longitude, latitude].every(Number.isFinite) || !Number.isFinite(Date.parse(String(origin.properties.timestamp)))) {
    throw new Error("Hindcast origin coordinates or time are invalid.");
  }
  progress("forecast");
  results.forward(await api.driftForward({ ...drift, duration_hours: forecastHours }));
  progress("ranking");
  results.attribution(await api.rankSuspects({
    ...ranking,
    origin_latitude: latitude,
    origin_longitude: longitude,
    estimated_origin_at: String(origin.properties.timestamp),
    use_hindcast_region: true,
  }));
}
