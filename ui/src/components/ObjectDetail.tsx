import { useQuery } from "@tanstack/react-query";
import { getObject, getRelationships } from "../api/client";
import type { StixObject } from "../types/stix";

export interface ObjectDetailProps {
  selectedId: string;
  onClose: () => void;
}

function pickString(obj: StixObject, key: string): string | undefined {
  const v = obj[key];
  return typeof v === "string" ? v : undefined;
}

export function ObjectDetail({ selectedId, onClose }: ObjectDetailProps) {
  const objectQuery = useQuery({
    queryKey: ["object", selectedId],
    queryFn: () => getObject(selectedId),
  });

  const relQuery = useQuery({
    queryKey: ["relationships", selectedId],
    queryFn: () => getRelationships(selectedId),
  });

  const obj = objectQuery.data?.object;

  return (
    <div className="object-detail">
      <div className="object-detail__header">
        <button type="button" className="object-detail__close" onClick={onClose} aria-label="Close detail">
          ×
        </button>
        <div className="object-detail__id">{selectedId}</div>
      </div>

      {objectQuery.isPending ? <p className="object-detail__muted">Loading…</p> : null}

      {objectQuery.isError ? <p className="object-detail__error">Failed to load object.</p> : null}

      {obj ? (
        <>
          <div className="object-detail__section-title">
            Relationships ({relQuery.data?.total ?? (relQuery.isPending ? "…" : 0)})
          </div>
          <div className="object-detail__rule" />
          {relQuery.isPending ? <p className="object-detail__muted">Loading relationships…</p> : null}
          {relQuery.isError ? <p className="object-detail__error">Failed to load relationships.</p> : null}
          {relQuery.data && relQuery.data.relationships.length > 0 ? (
            <ul className="object-detail__rels">
              {relQuery.data.relationships.map((rel) => {
                const rid = pickString(rel, "id") ?? "";
                const rtype = pickString(rel, "relationship_type") ?? "—";
                const target = pickString(rel, "target_ref") ?? "—";
                return (
                  <li key={rid || `${rtype}-${target}`}>
                    <span className="rel-type">{rtype}</span>
                    <span className="rel-arrow">→</span>
                    {target}
                  </li>
                );
              })}
            </ul>
          ) : null}
          {relQuery.isSuccess && relQuery.data.relationships.length === 0 ? (
            <p className="object-detail__muted">No relationships.</p>
          ) : null}

          <div className="object-detail__section-title">Raw STIX</div>
          <div className="object-detail__rule" />
          <pre className="object-detail__pre">
            <code>{JSON.stringify(obj, null, 2)}</code>
          </pre>
        </>
      ) : null}
    </div>
  );
}
