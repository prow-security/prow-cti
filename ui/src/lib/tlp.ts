import type { StixObject } from "../types/stix";

export type TlpLevel = "CLEAR" | "AMBER" | "RED";

function markingRefs(obj: StixObject): unknown {
  return obj.object_marking_refs;
}

/** Infer TLP from marking-definition references (substring match). */
export function inferTlp(obj: StixObject): TlpLevel {
  const refs = markingRefs(obj);
  if (!Array.isArray(refs)) return "CLEAR";
  for (const r of refs) {
    if (typeof r !== "string") continue;
    const low = r.toLowerCase();
    if (low.includes("tlp:red") || low.includes("tlp_red")) return "RED";
    if (low.includes("tlp:amber") || low.includes("tlp_amber")) return "AMBER";
  }
  return "CLEAR";
}

export function tlpLabel(level: TlpLevel): string {
  return `TLP:${level}`;
}
