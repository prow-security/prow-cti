export type SeverityBand = "critical" | "high" | "medium" | "low";

export function severityFromConfidence(confidence: number | undefined): SeverityBand {
  if (confidence === undefined || Number.isNaN(confidence)) return "low";
  if (confidence >= 90) return "critical";
  if (confidence >= 75) return "high";
  if (confidence >= 50) return "medium";
  return "low";
}

const COLORS: Record<SeverityBand, string> = {
  critical: "#dc2626",
  high: "#f97316",
  medium: "#eab308",
  low: "#9ca3af",
};

export function SeverityDot({ confidence }: { confidence: number | undefined }) {
  const band = severityFromConfidence(confidence);
  return (
    <span className="severity-dot" title={band}>
      <span className="severity-dot__inner" style={{ backgroundColor: COLORS[band] }} />
    </span>
  );
}
