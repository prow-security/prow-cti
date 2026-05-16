import { useQuery } from "@tanstack/react-query";
import { listObjects, searchObjects, type StixListSort } from "../api/client";
import { pickNumber, pickString } from "../lib/stixPick";
import type { StixObject } from "../types/stix";

export interface ObjectTableProps {
  searchQuery: string;
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** When set, list mode restricts to this STIX type. */
  objectType?: string;
  /** Sort for list mode (ignored in search mode). */
  listSort?: StixListSort;
}

function displayName(obj: StixObject): string {
  return pickString(obj, "name") ?? pickString(obj, "id") ?? "—";
}

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return `${s.slice(0, max)}…`;
}

function formatCreated(iso: string | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toISOString().slice(0, 10);
}

function rawCreated(obj: StixObject): string | undefined {
  return pickString(obj, "created");
}

export function ObjectTable({
  searchQuery,
  selectedId,
  onSelect,
  objectType,
  listSort = "ingested_at_desc",
}: ObjectTableProps) {
  const trimmed = searchQuery.trim();
  const listMode = trimmed.length === 0;

  const query = useQuery({
    queryKey: listMode
      ? ["objects", "list", objectType ?? "all", listSort]
      : ["objects", "search", trimmed, objectType ?? "all"],
    queryFn: () =>
      listMode
        ? listObjects({ type: objectType, limit: 100, offset: 0, sort: listSort })
        : searchObjects(trimmed, objectType, 50),
  });

  const colSpan = 5;

  return (
    <div className="object-table-wrap">
      <table className="object-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Created</th>
            <th>Confidence</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {query.isPending ? (
            <tr className="state-row">
              <td colSpan={colSpan}>Loading...</td>
            </tr>
          ) : query.isError ? (
            <tr className="state-row state-row--error">
              <td colSpan={colSpan}>Failed to load</td>
            </tr>
          ) : query.data.objects.length === 0 ? (
            <tr className="state-row">
              <td colSpan={colSpan}>
                No results
                <span className="empty-hint">Try a different search query, or clear search to browse all objects.</span>
              </td>
            </tr>
          ) : (
            query.data.objects.map((obj) => {
              const id = pickString(obj, "id");
              if (!id) return null;
              const name = displayName(obj);
              const nameShown = truncate(name, 60);
              const type = pickString(obj, "type") ?? "—";
              const createdIso = rawCreated(obj);
              const createdDay = formatCreated(createdIso);
              const conf = pickNumber(obj, "confidence");
              const confLabel = conf === undefined ? "—" : String(conf);
              const source = pickString(obj, "source_connector_instance_id") ?? "—";
              const selected = selectedId === id;
              return (
                <tr
                  key={id}
                  className={selected ? "row--selected" : undefined}
                  onClick={() => onSelect(id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelect(id);
                    }
                  }}
                  tabIndex={0}
                  role="button"
                  aria-pressed={selected}
                >
                  <td className="cell-name">
                    <span title={name}>{nameShown}</span>
                  </td>
                  <td>
                    <span className="type-badge" data-stix-type={type}>
                      {type}
                    </span>
                  </td>
                  <td className="cell-num" title={createdIso ?? undefined}>
                    {createdDay}
                  </td>
                  <td className="cell-num">{confLabel}</td>
                  <td className="cell-mono">{source}</td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
