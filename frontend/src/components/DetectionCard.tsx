import type { Detection } from "../api/client";
import { DetectionThumbnail } from "./DetectionThumbnail";
import { SeverityBadge } from "./SeverityBadge";

function formatTimestamp(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export function DetectionCard({ detection }: { detection: Detection }) {
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
          <SeverityBadge severity={detection.severity} />
        </div>
        <div className="detection-timestamp">{formatTimestamp(detection.captured_at)}</div>
        {typeof detection.risk_score === "number" && (
          <div className="detection-risk">Riesgo {Math.round(detection.risk_score)} / 100</div>
        )}
        {detection.alert && <div className="detection-alert">Alerta</div>}
        {detection.event && <div className="detection-event">{detection.event}</div>}
        {detection.summary && <p className="detection-summary">{detection.summary}</p>}
        {detection.recommended_action && (
          <p className="detection-action">
            <strong>Acción recomendada:</strong> {detection.recommended_action}
          </p>
        )}
      </div>
    </article>
  );
}
