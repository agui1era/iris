import type { SeverityLevel } from "../api/client";
import { useLanguage } from "../i18n/useLanguage";

const SEVERITY_LABELS: Record<SeverityLevel, [string, string]> = {
  none: ["Ninguna", "None"],
  info: ["Info", "Info"],
  low: ["Baja", "Low"],
  medium: ["Media", "Medium"],
  high: ["Alta", "High"],
  critical: ["Crítica", "Critical"],
};

function isSeverityLevel(value: string): value is SeverityLevel {
  return value in SEVERITY_LABELS;
}

export function SeverityBadge({ severity }: { severity: string | null }) {
  const { t } = useLanguage();
  const normalized = severity?.toLowerCase() ?? "none";
  const known = isSeverityLevel(normalized) ? normalized : "none";
  const label = isSeverityLevel(normalized)
    ? t(...SEVERITY_LABELS[normalized])
    : severity ?? "—";
  return <span className={`severity-badge severity-${known}`}>{label}</span>;
}
