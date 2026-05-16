import { useQuery } from "@tanstack/react-query";
import { getIngestStats } from "../api/client";
import { formatRelativeTime } from "../lib/relativeTime";
import { RecentIndicators } from "../components/RecentIndicators";
import { RiskFindings } from "../components/RiskFindings";
import { SourceChart } from "../components/SourceChart";
import { StatCard } from "../components/StatCard";

function formatPickerDate(d: Date): string {
  return new Intl.DateTimeFormat("en-US", { month: "long", day: "numeric", year: "numeric" }).format(d);
}

export function OverviewPage() {
  const stats = useQuery({ queryKey: ["ingest", "stats"], queryFn: getIngestStats });

  const byType = stats.data?.by_type ?? {};
  const indicators = typeof byType.indicator === "number" ? byType.indicator : 0;
  const vulns = typeof byType.vulnerability === "number" ? byType.vulnerability : 0;
  const total = stats.data?.total_objects ?? 0;
  const lastIngest = stats.data?.last_ingested_at
    ? formatRelativeTime(stats.data.last_ingested_at)
    : "—";

  return (
    <div className="overview">
      <header className="overview__top">
        <div>
          <h1 className="overview__h1">Overview</h1>
          <p className="overview__sub">Last 24 hours</p>
        </div>
        <button type="button" className="dash-btn dash-btn--outline">
          {formatPickerDate(new Date())} <span aria-hidden>▾</span>
        </button>
      </header>

      <section className="stat-cards" aria-label="Summary statistics">
        <StatCard label="Total Indicators" variant="blue" value={String(indicators)} trend="up" />
        <StatCard label="Vulnerabilities" variant="orange" value={String(vulns)} trend="up" />
        <StatCard label="STIX Objects" variant="grey" value={String(total)} trend="flat" />
        <StatCard label="Last Ingested" variant="ingest" value={lastIngest} trend="flat" pulse />
      </section>

      <section className="chart-row">
        <div className="chart-row__chart">
          <SourceChart />
        </div>
        <div className="chart-row__side">
          <RecentIndicators />
        </div>
      </section>

      <RiskFindings />
    </div>
  );
}
