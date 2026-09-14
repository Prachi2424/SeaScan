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
  closest_observed_distance_km: number;
  positions_in_time_window: number;
  behavior: {
    speed_drop: boolean | null;
    loitering: boolean | null;
    ais_gap_over_60_minutes: boolean | null;
    median_speed_knots?: number;
    reason?: string;
  };
  maximum_ais_gap_minutes: number;
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

export interface AttributionResponse {
  disclaimer: string;
  candidate_count: number;
  scoring_formula: Record<string, number>;
  candidates: CandidateVessel[];
}
