import type { SeverityLevel } from "../api/client";

const SEVERITY_LABELS: Record<SeverityLevel, string> = {
  none: "Ninguna",
  info: "Info",
  low: "Baja",
  medium: "Media",
  high: "Alta",
  critical: "Crítica",
};

function isSeverityLevel(value: string): value is SeverityLevel {
  return value in SEVERITY_LABELS;
}

export function SeverityBadge({ severity }: { severity: string | null }) {
  const normalized = severity?.toLowerCase() ?? "none";
  const known = isSeverityLevel(normalized) ? normalized : "none";
  const label = isSeverityLevel(normalized) ? SEVERITY_LABELS[normalized] : severity ?? "—";
  return <span className={`severity-badge severity-${known}`}>{label}</span>;
}
