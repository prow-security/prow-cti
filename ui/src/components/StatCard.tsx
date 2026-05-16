import { useId, useMemo, useState } from "react";
import { Area, AreaChart, ResponsiveContainer } from "recharts";
import type { SparkTrend } from "../lib/sparkline";
import { genSparkData } from "../lib/sparkline";

export interface StatCardProps {
  label: string;
  variant: "blue" | "orange" | "grey" | "ingest";
  value: string;
  trend: SparkTrend;
  /** When true, show green pulse dot next to value (last ingested card). */
  pulse?: boolean;
}

export function StatCard({ label, variant, value, trend, pulse }: StatCardProps) {
  const chartUid = useId().replace(/:/g, "");
  const [data] = useState(() => genSparkData(20, trend));
  const color = useMemo(() => {
    if (variant === "blue") return "#2563eb";
    if (variant === "orange") return "#ea580c";
    if (variant === "grey") return "#737373";
    return "#16a34a";
  }, [variant]);

  return (
    <div className="stat-card" data-variant={variant}>
      <div className="stat-card__label">{label}</div>
      <div className="stat-card__value-row">
        <div className="stat-card__value" style={{ color: variant === "ingest" ? "#15803d" : color }}>
          {value}
        </div>
        {pulse ? <span className="stat-card__pulse" aria-hidden /> : null}
      </div>
      {variant !== "ingest" ? (
        <div className="stat-card__spark">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id={`grad-${chartUid}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={color} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={color} stopOpacity={0} />
                </linearGradient>
              </defs>
              <Area
                type="monotone"
                dataKey="v"
                stroke={color}
                strokeWidth={1.5}
                fill={`url(#grad-${chartUid})`}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="stat-card__spark stat-card__spark--empty" />
      )}
    </div>
  );
}
