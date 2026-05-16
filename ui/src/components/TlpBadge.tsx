import type { StixObject } from "../types/stix";
import { inferTlp, tlpLabel, type TlpLevel } from "../lib/tlp";

const STYLES: Record<TlpLevel, { bg: string; fg: string }> = {
  CLEAR: { bg: "#dcfce7", fg: "#16a34a" },
  AMBER: { bg: "#fef3c7", fg: "#d97706" },
  RED: { bg: "#fee2e2", fg: "#dc2626" },
};

export function TlpBadge({ object }: { object: StixObject }) {
  const level = inferTlp(object);
  const s = STYLES[level];
  return (
    <span className="tlp-badge" style={{ backgroundColor: s.bg, color: s.fg }}>
      {tlpLabel(level)}
    </span>
  );
}
