export interface HealthResponse {
  status: "ok";
  service: string;
  version: string;
  timestamp: string;
}

export interface SystemConfigResponse {
  environment: string;
  max_upload_size_mb: number;
  accepted_satellite_formats: string[];
  accepted_ais_formats: string[];
  accepted_environmental_formats: string[];
  pipeline_stages: string[];
  satellite_inference_ready: boolean;
}

// ---------------------------------------------------------------------------
// Investigations
// ---------------------------------------------------------------------------

export interface InvestigationCreate {
  title: string;
  description?: string;
}

export interface InvestigationSummary {
  id: string;
  title: string;
  description: string;
  created_at: string;
  updated_at: string;
}

export type AssetType = "satellite" | "ais" | "environment";

export interface EvidenceProvenance {
  evidence_kind: "real" | "synthetic" | "unknown";
  source_organization: string;
  source_reference: string;
  dataset_version: string;
  acquired_at: string | null;
  declared_crs: string;
  prior_processing: string;
  added_by: string;
}

export interface EvidenceAsset {
  id: string;
  investigation_id: string;
  asset_type: AssetType;
  original_filename: string;
  media_type: string | null;
  byte_size: number;
  sha256: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface InvestigationDetail extends InvestigationSummary {
  assets: EvidenceAsset[];
  analyses: {
    release_scenarios?: ReleaseScenarioResponse;
    satellite_detection?: SatelliteDetectionResponse;
    drift_backward?: DriftResponse;
    drift_forward?: DriftResponse;
    attribution?: AttributionResponse;
  };
}

// ---------------------------------------------------------------------------
// Ingestion
// ---------------------------------------------------------------------------

export interface IngestionResponse {
  asset: EvidenceAsset;
  validation: Record<string, unknown>;
}

export interface SatelliteDetectionResponse extends IngestionResponse {
  geojson: GeoJSON.FeatureCollection;
  model: Record<string, unknown>;
}

export interface SatellitePresentation {
  imageUrl: string | null;
  groundTruthUrl: string | null;
  bounds: [number, number, number, number] | null;
  filename: string;
}

// ---------------------------------------------------------------------------
// Forensics — drift
// ---------------------------------------------------------------------------

export interface DriftRequest {
  environmental_asset_id: string;
  latitude: number;
  longitude: number;
  observed_at: string;
  duration_hours: number;
  step_minutes?: number;
  particle_count?: number;
  initial_spread_meters?: number;
  windage_factor?: number;
  random_seed?: number;
}

export interface DriftResponse {
  parameters?: DriftRequest | null;
  direction: "forward" | "backward";
  seed: Record<string, unknown>;
  trajectory: GeoJSON.FeatureCollection;
  probability_region: GeoJSON.Feature;
  sampling: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Forensics — attribution
// ---------------------------------------------------------------------------

export interface AttributionRequest {
  use_hindcast_region?: boolean;
  ais_asset_id: string;
  origin_latitude: number;
  origin_longitude: number;
  estimated_origin_at: string;
  search_radius_km?: number;
  temporal_window_minutes?: number;
  behavior_window_hours?: number;
}

export interface ScoreBreakdown {
  proximity: number;
  temporal: number;
  trajectory: number;
  behavioral_anomaly: number;
  vessel_type: number;
  ais_consistency: number;
}

export interface CandidateEvidence {
  closest_observed_distance_km: number | null;
  closest_approach_distance_km?: number;
  closest_approach_at?: string;
  closest_approach_interpolated?: boolean;
  origin_region_intersection?: boolean | null;
  heading_alignment?: number | null;
  warnings?: string[];
  positions_in_time_window: number;
  behavior: {
    speed_drop: boolean | null;
    loitering: boolean | null;
    ais_gap_over_60_minutes: boolean | null;
    median_speed_knots?: number;
    reason?: string;
  };
  maximum_ais_gap_minutes: number | null;
  score_note: string;
}

export interface CandidateVessel {
  mmsi: string;
  vessel_type: string | null;
  evidence_score: number;
  score_breakdown: ScoreBreakdown;
  evidence: CandidateEvidence;
  track_geojson: GeoJSON.Feature;
}

export interface VesselTrackPosition {
  timestamp: string;
  latitude: number;
  longitude: number;
  distance_to_origin_km: number;
  speed_knots: number | null;
  course_degrees: number | null;
}

export interface AttributionResponse {
  excluded_vessels?: { mmsi: string; reason: string }[];
  ranking_version?: string;
  parameters?: AttributionRequest | null;
  disclaimer: string;
  candidate_count: number;
  scoring_formula: Record<string, number>;
  candidates: CandidateVessel[];
}

// ---------------------------------------------------------------------------
// Phase 6 — immutable forensic report export
// ---------------------------------------------------------------------------

export interface ForensicReportRequest {
  investigation_id: string;
}

export interface ReleaseScenarioRequest {
  drift: DriftRequest;
  ais_asset_id: string;
  durations_hours: number[];
  search_radius_km: number;
  temporal_window_minutes: number;
}
export interface ReleaseScenarioResponse {
  parameters: ReleaseScenarioRequest;
  disclaimer: string;
  scenarios: {
    duration_hours: number;
    status: string;
    error?: string;
    origin?: GeoJSON.Feature<GeoJSON.Point>;
    candidate_count?: number;
    candidates?: CandidateVessel[];
    sampling?: { warnings?: string[] };
  }[];
}
