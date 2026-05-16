/** Map connector instance IDs to human-readable source names. */
export const SOURCE_LABELS: Record<string, string> = {
  dev: "CISA KEV",
  "cisa-kev": "CISA KEV",
  "mitre-attack": "MITRE ATT&CK",
  urlhaus: "abuse.ch URLhaus",
  threatfox: "ThreatFox",
  misp: "MISP",
};

export function sourceLabel(id: string): string {
  return SOURCE_LABELS[id] ?? id;
}
