import { useQuery } from "@tanstack/react-query";
import { listObjects } from "../api/client";
import { formatRelativeTime } from "../lib/relativeTime";
import { pickNumber, pickString } from "../lib/stixPick";
import type { StixObject } from "../types/stix";
import { TlpBadge } from "./TlpBadge";
import { TypeIcon } from "./TypeIcon";

function displayName(obj: StixObject): string {
  return pickString(obj, "name") ?? pickString(obj, "id") ?? "—";
}

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return `${s.slice(0, max)}…`;
}

function lastSeenIso(obj: StixObject): string | undefined {
  return pickString(obj, "ingested_at") ?? pickString(obj, "created");
}

export function RecentIndicators() {
  const q = useQuery({
    queryKey: ["objects", "recent-indicators"],
    queryFn: () => listObjects({ type: "indicator", limit: 5, offset: 0, sort: "created_desc" }),
  });

  return (
    <section className="dash-panel dash-panel--recent">
      <div className="dash-panel__head">
        <h2 className="dash-panel__title">Recent Indicators</h2>
      </div>
      <div className="dash-table-wrap">
        <table className="dash-table">
          <thead>
            <tr>
              <th>Indicator/Object</th>
              <th>TLP</th>
              <th className="num">Confidence</th>
              <th className="muted">Last Seen</th>
            </tr>
          </thead>
          <tbody>
            {q.isPending ? (
              <tr>
                <td colSpan={4} className="dash-table__state">
                  Loading…
                </td>
              </tr>
            ) : q.isError ? (
              <tr>
                <td colSpan={4} className="dash-table__state dash-table__state--error">
                  Failed to load
                </td>
              </tr>
            ) : (
              q.data.objects.map((obj) => {
                const id = pickString(obj, "id");
                if (!id) return null;
                const name = displayName(obj);
                const conf = pickNumber(obj, "confidence");
                return (
                  <tr key={id}>
                    <td>
                      <div className="dash-cell-name">
                        <TypeIcon stixType="indicator" />
                        <span title={name}>{truncate(name, 30)}</span>
                      </div>
                    </td>
                    <td>
                      <TlpBadge object={obj} />
                    </td>
                    <td className="num">{conf === undefined ? "—" : conf}</td>
                    <td className="muted">{formatRelativeTime(lastSeenIso(obj))}</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
      <div className="dash-panel__foot">
        <button type="button" className="dash-link">
          View all
        </button>
      </div>
    </section>
  );
}
