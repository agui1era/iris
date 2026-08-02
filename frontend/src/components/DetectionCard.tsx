import type { Detection } from "../api/client";
import { CriticalityBadge } from "./CriticalityBadge";
import { DetectionThumbnail } from "./DetectionThumbnail";
import { SeverityBadge } from "./SeverityBadge";
import { useLanguage } from "../i18n/useLanguage";
import { analysisEventLabel, analysisMessageLabel } from "../i18n/analysisLabels";

function formatTimestamp(value: string | null, locale: string): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(locale);
}

interface DetectionCardProps {
  detection: Detection;
  /** Present only for admins; omit to hide the delete button entirely. */
  onDelete?: () => void;
  deleting?: boolean;
}

export function DetectionCard({ detection, onDelete, deleting = false }: DetectionCardProps) {
  const { language, locale, t } = useLanguage();
  const cameraLabel = detection.camera_name ?? detection.camera_id ?? t("Cámara desconocida", "Unknown camera");

  return (
    <article className="detection-card">
      <div className="detection-media">
        {detection.has_image ? (
          <DetectionThumbnail
            id={detection.id}
            alt={detection.event ? analysisEventLabel(detection.event, language) : cameraLabel}
          />
        ) : (
          <div className="thumb thumb-empty">{t("Sin imagen", "No image")}</div>
        )}
      </div>
      <div className="detection-body">
        <div className="detection-header">
          <span className="detection-camera">{cameraLabel}</span>
          <div className="badge-group">
            <SeverityBadge severity={detection.severity} />
            <CriticalityBadge criticidad={detection.criticidad} />
          </div>
        </div>
        <div className="detection-timestamp">{formatTimestamp(detection.captured_at, locale)}</div>
        {typeof detection.risk_score === "number" && (
          <div className="detection-risk">{t("Riesgo", "Risk")} {Math.round(detection.risk_score)} / 100</div>
        )}
        {typeof detection.confidence === "number" && (
          <div className="detection-confidence">
            {t("Confianza IA", "AI confidence")} {Math.round(detection.confidence * 100)}%
          </div>
        )}
        {detection.alert && <div className="detection-alert">{t("Alerta", "Alert")}</div>}
        {detection.event && (
          <div className="detection-event">{analysisEventLabel(detection.event, language)}</div>
        )}
        {detection.summary && (
          <p className="detection-summary">
            {analysisMessageLabel(detection.summary, language)}
          </p>
        )}
        {detection.recommended_action && (
          <p className="detection-action">
            <strong>{t("Acción recomendada:", "Recommended action:")}</strong>{" "}
            {analysisMessageLabel(detection.recommended_action, language)}
          </p>
        )}
        {onDelete && (
          <button
            type="button"
            className="btn btn-ghost detection-delete"
            onClick={onDelete}
            disabled={deleting}
          >
            {deleting ? t("Eliminando…", "Deleting…") : t("Eliminar", "Delete")}
          </button>
        )}
      </div>
    </article>
  );
}
