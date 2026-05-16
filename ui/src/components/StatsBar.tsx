import { useQuery } from "@tanstack/react-query";
import { getIngestStats } from "../api/client";

const nf = new Intl.NumberFormat("en-US");

export function StatsBar() {
  const { data, isPending } = useQuery({
    queryKey: ["ingest-stats"],
    queryFn: getIngestStats,
    refetchInterval: 60_000,
  });

  if (isPending || !data) {
    return <div className="stats-bar">…</div>;
  }

  const indicators = data.by_type.indicator ?? 0;
  const vulnerabilities = data.by_type.vulnerability ?? 0;

  return (
    <div className="stats-bar">
      <span>{nf.format(data.total_objects)} objects</span>
      <span className="stats-bar__sep" aria-hidden="true">
        ·
      </span>
      <span>{nf.format(indicators)} indicators</span>
      <span className="stats-bar__sep" aria-hidden="true">
        ·
      </span>
      <span>{nf.format(vulnerabilities)} vulnerabilities</span>
    </div>
  );
}
