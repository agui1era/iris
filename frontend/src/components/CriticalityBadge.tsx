import { useLanguage } from "../i18n/useLanguage";

const CRITICALITY_LABELS: Record<string, [string, string]> = {
  verde: ["Verde", "Green"],
  amarillo: ["Amarillo", "Yellow"],
  naranja: ["Naranja", "Orange"],
  rojo: ["Rojo", "Red"],
};

function isCriticalityColor(value: string): value is keyof typeof CRITICALITY_LABELS {
  return value in CRITICALITY_LABELS;
}

/** Shows the model's own independent color judgment, separate from IRIS's calculated severity. */
export function CriticalityBadge({ criticidad }: { criticidad: string | null | undefined }) {
  const { t } = useLanguage();
  const normalized = criticidad?.toLowerCase().trim() ?? "";
  if (!normalized) {
    return <span className="criticality-badge criticality-negro">{t("Sin datos", "No data")}</span>;
  }
  const known = isCriticalityColor(normalized);
  const label = known ? t(...CRITICALITY_LABELS[normalized]) : criticidad;
  return (
    <span className={`criticality-badge criticality-${known ? normalized : "negro"}`}>
      {label}
    </span>
  );
}
