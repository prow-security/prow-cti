/** STIX objects as returned by the API (JSON-decoded). */
export type StixObject = Record<string, unknown>;

export interface ObjectListResponse {
  objects: StixObject[];
  total: number;
  limit: number;
  offset: number;
}

export interface SearchResponse {
  objects: StixObject[];
  total: number;
}

export interface StixObjectEnvelope {
  object: StixObject;
}

export interface RelationshipListResponse {
  relationships: StixObject[];
  total: number;
}

export interface IngestStats {
  total_objects: number;
  by_type: Record<string, number>;
  last_ingested_at: string | null;
}

export interface HealthResponse {
  status: string;
  version: string;
  detail: string | null;
}

export interface IngestTimeseriesDay {
  date: string;
  indicator: number;
  vulnerability: number;
}

export interface IngestTimeseriesResponse {
  days: number;
  series: IngestTimeseriesDay[];
}
