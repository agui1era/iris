const CRITICALITY_LABELS: Record<string, string> = {
  verde: "Verde",
  amarillo: "Amarillo",
  naranja: "Naranja",
  rojo: "Rojo",
};

function isCriticalityColor(value: string): value is keyof typeof CRITICALITY_LABELS {
  return value in CRITICALITY_LABELS;
}

/** Shows the model's own independent color judgment, separate from IRIS's calculated severity. */
export function CriticalityBadge({ criticidad }: { criticidad: string | null | undefined }) {
  const normalized = criticidad?.toLowerCase().trim() ?? "";
  if (!normalized) {
    return <span className="criticality-badge criticality-negro">Sin datos</span>;
  }
  const known = isCriticalityColor(normalized);
  const label = known ? CRITICALITY_LABELS[normalized] : criticidad;
  return (
    <span className={`criticality-badge criticality-${known ? normalized : "negro"}`}>
      {label}
    </span>
  );
}
