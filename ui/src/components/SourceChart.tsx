import { useId, useMemo } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";

/** Plausible stacked counts for the multi-source preview (not from live connectors). */
function buildFakeSourceSeries(): Array<Record<string, string | number>> {
  const days = ["Apr 17", "Apr 22", "Apr 27", "May 2", "May 7", "May 12", "May 16"];
  return days.map((d, i) => {
    const t = i / (days.length - 1);
    const kev = Math.round(800 + t * 750 + Math.sin(i) * 40);
    const mitre = Math.round(200 + t * 180 + Math.cos(i) * 30);
    const urlhaus = Math.round(120 + t * 90);
    const fox = Math.round(80 + t * 70);
    return { d, kev, mitre, urlhaus, fox };
  });
}

export function SourceChart() {
  const data = useMemo(() => buildFakeSourceSeries(), []);
  const gid = useId().replace(/:/g, "");

  return (
    <div className="source-chart">
      <div className="source-chart__head">
        <h2 className="source-chart__title">Indicators by Source — Last 30 days</h2>
        <button type="button" className="dash-btn dash-btn--ghost">
          Last 30 days <span aria-hidden>▾</span>
        </button>
      </div>
      <div className="source-chart__plot">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id={`${gid}-kev`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.35} />
                <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.08} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#ecece8" vertical={false} />
            <XAxis dataKey="d" tick={{ fontSize: 11, fill: "#6b6b68" }} axisLine={{ stroke: "#e5e5e3" }} />
            <YAxis
              domain={[0, 10000]}
              ticks={[0, 2500, 5000, 7500, 10000]}
              tick={{ fontSize: 11, fill: "#6b6b68" }}
              axisLine={{ stroke: "#e5e5e3" }}
              tickFormatter={(v) => {
                if (v >= 1000 && v % 1000 === 0) return `${v / 1000}K`;
                if (v >= 1000) return `${(v / 1000).toFixed(1)}K`;
                return String(v);
              }}
            />
            <Legend verticalAlign="bottom" wrapperStyle={{ paddingTop: 12 }} iconType="circle" />
            <Area
              type="monotone"
              dataKey="kev"
              name="CISA KEV"
              stackId="a"
              stroke="#3b82f6"
              fill={`url(#${gid}-kev)`}
              fillOpacity={1}
            />
            <Area type="monotone" dataKey="mitre" name="MITRE ATT&CK" stackId="a" stroke="#8b5cf6" fill="#8b5cf6" fillOpacity={0.85} />
            <Area type="monotone" dataKey="urlhaus" name="abuse.ch URLhaus" stackId="a" stroke="#f59e0b" fill="#f59e0b" fillOpacity={0.85} />
            <Area type="monotone" dataKey="fox" name="ThreatFox" stackId="a" stroke="#ef4444" fill="#ef4444" fillOpacity={0.85} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
