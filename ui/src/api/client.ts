import type {
  HealthResponse,
  IngestStats,
  IngestTimeseriesResponse,
  ObjectListResponse,
  RelationshipListResponse,
  SearchResponse,
  StixObjectEnvelope,
} from "../types/stix";

const API = "";

export type StixListSort = "confidence_desc" | "created_desc" | "ingested_at_desc";

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export interface ListObjectsParams {
  type?: string;
  limit?: number;
  offset?: number;
  sort?: StixListSort;
}

export const listObjects = (params?: ListObjectsParams) => {
  const { type, limit = 100, offset = 0, sort = "ingested_at_desc" } = params ?? {};
  const sp = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
    sort,
    ...(type ? { type } : {}),
  });
  return apiFetch<ObjectListResponse>(`/api/v1/objects?${sp}`);
};

export const searchObjects = (q: string, type?: string, limit = 50) =>
  apiFetch<SearchResponse>(
    `/api/v1/search?${new URLSearchParams({
      q,
      ...(type ? { type } : {}),
      limit: String(limit),
    })}`,
  );

export const getObject = (stixId: string) =>
  apiFetch<StixObjectEnvelope>(`/api/v1/objects/${encodeURIComponent(stixId)}`);

export const getRelationships = (stixId: string) =>
  apiFetch<RelationshipListResponse>(
    `/api/v1/objects/${encodeURIComponent(stixId)}/relationships`,
  );

export const getIngestStats = () => apiFetch<IngestStats>("/api/v1/ingest/stats");

export const getIngestTimeseries = (days = 30) =>
  apiFetch<IngestTimeseriesResponse>(`/api/v1/stats/timeseries?${new URLSearchParams({ days: String(days) })}`);

export const getHealth = () => apiFetch<HealthResponse>("/health");
