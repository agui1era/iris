import type { Detection } from "../api/client";
import { CriticalityBadge } from "./CriticalityBadge";
import { DetectionThumbnail } from "./DetectionThumbnail";
import { SeverityBadge } from "./SeverityBadge";

function formatTimestamp(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

interface DetectionCardProps {
  detection: Detection;
  /** Present only for admins; omit to hide the delete button entirely. */
  onDelete?: () => void;
  deleting?: boolean;
}

export function DetectionCard({ detection, onDelete, deleting = false }: DetectionCardProps) {
  const cameraLabel = detection.camera_name ?? detection.camera_id ?? "Cámara desconocida";

  return (
    <article className="detection-card">
      <div className="detection-media">
        {detection.has_image ? (
          <DetectionThumbnail id={detection.id} alt={detection.event ?? cameraLabel} />
        ) : (
          <div className="thumb thumb-empty">Sin imagen</div>
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
        <div className="detection-timestamp">{formatTimestamp(detection.captured_at)}</div>
        {typeof detection.risk_score === "number" && (
          <div className="detection-risk">Riesgo {Math.round(detection.risk_score)} / 100</div>
        )}
        {typeof detection.confidence === "number" && (
          <div className="detection-confidence">
            Confianza IA {Math.round(detection.confidence * 100)}%
          </div>
        )}
        {detection.alert && <div className="detection-alert">Alerta</div>}
        {detection.event && <div className="detection-event">{detection.event}</div>}
        {detection.summary && <p className="detection-summary">{detection.summary}</p>}
        {detection.recommended_action && (
          <p className="detection-action">
            <strong>Acción recomendada:</strong> {detection.recommended_action}
          </p>
        )}
        {onDelete && (
          <button
            type="button"
            className="btn btn-ghost detection-delete"
            onClick={onDelete}
            disabled={deleting}
          >
            {deleting ? "Eliminando…" : "Eliminar"}
          </button>
        )}
      </div>
    </article>
  );
}
