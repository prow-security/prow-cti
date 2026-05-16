import { useQuery } from "@tanstack/react-query";
import { listObjects } from "../api/client";
import { formatRelativeTime } from "../lib/relativeTime";
import { sourceLabel } from "../lib/sourceLabels";
import { pickNumber, pickString } from "../lib/stixPick";
import type { StixObject } from "../types/stix";
import { SeverityDot } from "./SeverityDot";
import { TypeIcon } from "./TypeIcon";

function displayName(obj: StixObject): string {
  return pickString(obj, "name") ?? pickString(obj, "id") ?? "—";
}

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return `${s.slice(0, max)}…`;
}

function detectionLabel(obj: StixObject, sourceId: string): string {
  const rawTypes = obj.indicator_types;
  if (Array.isArray(rawTypes) && rawTypes.length > 0) {
    const parts = rawTypes
      .map((t) => (typeof t === "string" ? t : null))
      .filter((t): t is string => Boolean(t));
    if (parts.length > 0) return parts.join(", ");
  }
  if (sourceId === "dev" || sourceId === "cisa-kev") {
    return "Known Exploited Vulnerability";
  }
  return "—";
}

function lastSeenIso(obj: StixObject): string | undefined {
  return pickString(obj, "ingested_at") ?? pickString(obj, "created");
}

export function RiskFindings() {
  const q = useQuery({
    queryKey: ["objects", "risk-findings"],
    queryFn: () => listObjects({ type: "indicator", limit: 10, offset: 0, sort: "confidence_desc" }),
  });

  return (
    <section className="dash-panel dash-panel--full">
      <div className="dash-panel__head dash-panel__head--split">
        <h2 className="dash-panel__title">Top Risk Findings</h2>
        <button type="button" className="dash-link">
          View all
        </button>
      </div>
      <div className="dash-table-wrap">
        <table className="dash-table dash-table--risk">
          <thead>
            <tr>
              <th className="col-sev">Severity</th>
              <th>Indicator/Object</th>
              <th>Source</th>
              <th>Type/Detection</th>
              <th className="muted">Last Seen</th>
              <th className="col-actions" aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {q.isPending ? (
              <tr>
                <td colSpan={6} className="dash-table__state">
                  Loading…
                </td>
              </tr>
            ) : q.isError ? (
              <tr>
                <td colSpan={6} className="dash-table__state dash-table__state--error">
                  Failed to load
                </td>
              </tr>
            ) : (
              q.data.objects.map((obj) => {
                const id = pickString(obj, "id");
                if (!id) return null;
                const name = displayName(obj);
                const src = pickString(obj, "source_connector_instance_id") ?? "—";
                const conf = pickNumber(obj, "confidence");
                return (
                  <tr key={id}>
                    <td className="col-sev">
                      <SeverityDot confidence={conf} />
                    </td>
                    <td>
                      <div className="dash-cell-name">
                        <TypeIcon stixType="indicator" />
                        <span title={name}>{truncate(name, 42)}</span>
                      </div>
                    </td>
                    <td>{sourceLabel(src)}</td>
                    <td className="muted">{detectionLabel(obj, src)}</td>
                    <td className="muted">{formatRelativeTime(lastSeenIso(obj))}</td>
                    <td className="col-actions">
                      <button type="button" className="icon-btn" aria-label="More">
                        ···
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
