import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  fetchDashboard,
  type DashboardCamera,
  type DashboardResponse,
} from "../api/client";
import { CriticalityBadge } from "../components/CriticalityBadge";
import { DashboardCapture } from "../components/DashboardCapture";
import { SeverityBadge } from "../components/SeverityBadge";
import { useLanguage } from "../i18n/useLanguage";
import { analysisEventLabel, analysisMessageLabel } from "../i18n/analysisLabels";

const UI_POLL_INTERVAL_MS = 3_000;
const ALERT_SEVERITIES = new Set(["high", "critical"]);

type Translate = (spanish: string, english: string) => string;

function formatClock(value: string | null, locale: string, t: Translate): string {
  if (!value) return t("Sin registro", "No record");
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return t("Hora desconocida", "Unknown time");
  return new Intl.DateTimeFormat(locale, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function relativeTime(value: string | null, now: number, t: Translate): string {
  if (!value) return t("sin actividad", "no activity");
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return t("hora desconocida", "unknown time");
  const seconds = Math.max(0, Math.round((now - timestamp) / 1_000));
  if (seconds < 10) return t("ahora", "now");
  if (seconds < 60) return t(`hace ${seconds} s`, `${seconds}s ago`);
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return t(`hace ${minutes} min`, `${minutes} min ago`);
  return t(`hace ${Math.floor(minutes / 60)} h`, `${Math.floor(minutes / 60)}h ago`);
}

function isCameraOnline(camera: DashboardCamera): boolean {
  return camera.status.toLowerCase() === "online";
}

function cameraStatusMeta(camera: DashboardCamera, t: Translate): {
  kind: "online" | "offline" | "waiting" | "unknown";
  label: string;
} {
  const normalized = camera.status.toLowerCase();
  if (normalized === "online") return { kind: "online", label: t("En línea", "Online") };
  if (normalized === "offline") return { kind: "offline", label: t("Fuera de línea", "Offline") };
  if (normalized === "waiting") return { kind: "waiting", label: t("Esperando señal", "Waiting for signal") };
  return { kind: "unknown", label: t("Estado desconocido", "Unknown status") };
}

function captureDiagnostic(
  status: "online" | "offline" | "waiting" | "unknown",
  pollIntervalSeconds: number,
  t: Translate,
): string {
  if (status === "offline") {
    return t("Sin conexión RTSP. Revisa URL, credenciales y acceso de red.", "No RTSP connection. Check the URL, credentials, and network access.");
  }
  if (status === "waiting") {
    return t(`Esperando la primera conexión; una captura puede tardar hasta ${pollIntervalSeconds} s.`, `Waiting for the first connection; a capture may take up to ${pollIntervalSeconds}s.`);
  }
  if (status === "unknown") {
    return t("Sin estado de conectividad reciente. Revisa el stream si no aparece una captura.", "No recent connectivity status. Check the stream if a capture does not appear.");
  }
  return t(`Cámara conectada; esperando el próximo análisis (polling cada ${pollIntervalSeconds} s).`, `Camera connected; waiting for the next analysis (polling every ${pollIntervalSeconds}s).`);
}

function analysisStateMeta(camera: DashboardCamera, t: Translate): {
  label: string;
  note: string | null;
} {
  if (camera.latest_analysis_status === "failed") {
    return {
      label: t("ÚLTIMO INTENTO FALLÓ", "LATEST ATTEMPT FAILED"),
      note: camera.last_event
        ? t("El último análisis falló; se conserva abajo la última lectura válida.", "The latest analysis failed; the last valid reading is kept below.")
        : t("El último análisis falló y todavía no existe una lectura válida.", "The latest analysis failed and there is no valid reading yet."),
    };
  }
  if (camera.latest_analysis_status === "pending") {
    return {
      label: t("PROCESANDO", "PROCESSING"),
      note: camera.last_event
        ? t("Hay una captura más reciente en proceso; la lectura visible corresponde al último análisis terminado.", "A newer capture is being processed; the visible reading is from the latest completed analysis.")
        : t("La primera captura está esperando o siendo procesada.", "The first capture is waiting or being processed."),
    };
  }
  if (camera.latest_analysis_status === "unavailable") {
    return {
      label: t("HISTORIAL NO DISPONIBLE", "HISTORY UNAVAILABLE"),
      note: t("La captura sigue operativa, pero no se pudo consultar el estado semántico.", "Capture remains operational, but the semantic status could not be retrieved."),
    };
  }
  if (camera.latest_analysis_status === "completed") {
    return { label: t("COMPLETADO", "COMPLETED"), note: null };
  }
  return { label: t("SIN LECTURAS", "NO READINGS"), note: null };
}

export function MonitoringPage() {
  const { language, locale, t } = useLanguage();
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const requestInFlightRef = useRef(false);

  const load = useCallback(async (manual = false) => {
    if (requestInFlightRef.current) return;
    requestInFlightRef.current = true;
    if (manual) setRefreshing(true);
    try {
      const data = await fetchDashboard();
      setDashboard(data);
      setError(null);
      setUpdatedAt(new Date());
    } catch (caught) {
      const message =
        caught instanceof ApiError
          ? caught.message
          : t("No se pudo conectar con el servicio de monitoreo.", "Could not connect to the monitoring service.");
      setError(message);
    } finally {
      requestInFlightRef.current = false;
      setLoading(false);
      setRefreshing(false);
    }
  }, [t]);

  useEffect(() => {
    let cancelled = false;
    let poller: number | undefined;

    const poll = async () => {
      await load();
      if (!cancelled) poller = window.setTimeout(() => void poll(), UI_POLL_INTERVAL_MS);
    };

    void poll();
    return () => {
      cancelled = true;
      if (poller !== undefined) window.clearTimeout(poller);
    };
  }, [load]);

  useEffect(() => {
    const clock = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(clock);
  }, []);

  const metrics = useMemo(() => {
    const cameras = dashboard?.cameras ?? [];
    const online = cameras.filter(isCameraOnline).length;
    const alerts = cameras.filter((camera) => {
      const analysis = camera.last_event?.analysis;
      if (typeof analysis?.risk_score === "number") {
        return analysis.risk_score >= 70;
      }
      return Boolean(
        analysis?.alert ||
          ALERT_SEVERITIES.has(analysis?.severity?.toLowerCase() ?? ""),
      );
    }).length;
    const riskScores = cameras
      .map((camera) => camera.last_event?.analysis?.risk_score)
      .filter((value): value is number => typeof value === "number");
    const averageRisk =
      riskScores.length > 0
        ? riskScores.reduce((sum, value) => sum + value, 0) / riskScores.length
        : null;
    const pollingIntervals = cameras.map((camera) => camera.poll_interval_seconds);
    const pollingRange =
      pollingIntervals.length === 0
        ? "—"
        : Math.min(...pollingIntervals) === Math.max(...pollingIntervals)
          ? String(Math.min(...pollingIntervals))
          : `${Math.min(...pollingIntervals)}–${Math.max(...pollingIntervals)}`;
    return { online, alerts, averageRisk, pollingRange };
  }, [dashboard]);

  if (loading && !dashboard) {
    return (
      <div className="monitor-page" aria-busy="true">
        <div className="monitor-page-heading">
          <div>
            <span className="eyebrow">{t("OPERACIÓN EN TIEMPO REAL", "REAL-TIME OPERATIONS")}</span>
            <h1>{t("Centro de monitoreo", "Monitoring center")}</h1>
          </div>
        </div>
        <div className="monitor-skeleton-grid" aria-label={t("Cargando cámaras", "Loading cameras")}>
          {[0, 1, 2, 3].map((item) => (
            <div className="monitor-skeleton-card" key={item} />
          ))}
        </div>
      </div>
    );
  }

  if (!dashboard) {
    return (
      <div className="monitor-page">
        <div className="empty-state error-state" role="alert">
          <span className="empty-state-mark" aria-hidden="true">
            !
          </span>
          <h1>{t("Monitoreo no disponible", "Monitoring unavailable")}</h1>
          <p>{error ?? t("El servicio no respondió.", "The service did not respond.")}</p>
          <button type="button" className="btn btn-primary" onClick={() => void load(true)}>
            {t("Reintentar conexión", "Retry connection")}
          </button>
        </div>
      </div>
    );
  }

  const cameras = dashboard.cameras;

  return (
    <div className="monitor-page">
      <div className="monitor-page-heading">
        <div>
          <span className="eyebrow">{t("OPERACIÓN EN TIEMPO REAL", "REAL-TIME OPERATIONS")}</span>
          <h1>{t("Centro de monitoreo", "Monitoring center")}</h1>
          <p>{t("Capturas relevantes, riesgo operacional y análisis inteligente.", "Relevant captures, operational risk, and intelligent analysis.")}</p>
        </div>
        <div className="monitor-refresh">
          <span className="refresh-copy" aria-live="polite">
            {updatedAt ? t(`Sincronizado ${formatClock(updatedAt.toISOString(), locale, t)}`, `Synced ${formatClock(updatedAt.toISOString(), locale, t)}`) : t("Sin sincronizar", "Not synced")}
          </span>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => void load(true)}
            disabled={refreshing}
          >
            {refreshing ? t("Sincronizando…", "Syncing…") : t("Actualizar ahora", "Refresh now")}
          </button>
        </div>
      </div>

      {error && (
        <div className="alert alert-warning" role="alert">
          {t(`Se perdió la última sincronización: ${error}. Se mantienen los últimos datos recibidos.`, `The latest sync failed: ${error}. The last received data is still displayed.`)}
        </div>
      )}

      <section className="monitor-metrics" aria-label={t("Resumen del monitoreo", "Monitoring summary")}>
        <div className="metric-card">
          <span className="metric-label">{t("Cámaras activas", "Active cameras")}</span>
          <strong>
            {metrics.online}
            <small> / {cameras.length}</small>
          </strong>
          <span className="metric-foot positive">● {t("señal reciente", "recent signal")}</span>
        </div>
        <div className="metric-card">
          <span className="metric-label">{t("Alertas actuales", "Current alerts")}</span>
          <strong>{metrics.alerts}</strong>
          <span className={metrics.alerts > 0 ? "metric-foot warning" : "metric-foot muted"}>
            {metrics.alerts > 0 ? t("requieren atención", "require attention") : t("sin alertas críticas", "no critical alerts")}
          </span>
        </div>
        <div className="metric-card">
          <span className="metric-label">{t("Riesgo promedio", "Average risk")}</span>
          <strong>{metrics.averageRisk === null ? "—" : Math.round(metrics.averageRisk)}</strong>
          <span className="metric-foot muted">{t("riesgo promedio / 100", "average risk / 100")}</span>
        </div>
        <div className="metric-card">
          <span className="metric-label">{t("Polling por cámara", "Polling per camera")}</span>
          <strong>
            {metrics.pollingRange}
            <small> s</small>
          </strong>
          <span className="metric-foot muted">{t("mínimo 10 s · interfaz cada 3 s", "minimum 10s · interface every 3s")}</span>
        </div>
      </section>

      <div className="score-explainer">
        <span aria-hidden="true">i</span>
        <p>
          {t(
            "Risk score mide urgencia operacional de 0 a 100. Confianza indica cuán seguro está el modelo de su lectura; es una medida separada y no equivale a riesgo. Bandas: 0–9 sin riesgo, 10–29 informativa, 30–49 baja, 50–69 media, 70–89 alta y 90–100 crítica. Severidad (badge izquierdo) la calcula IRIS siempre a partir del risk score. Criticidad (badge derecho, verde/amarillo/naranja/rojo) es la lectura propia e independiente del modelo sobre la misma escena; se muestra a título informativo y nunca reemplaza a la severidad. Negro significa que todavía no hay análisis para esa cámara.",
            "Risk score measures operational urgency from 0 to 100. Confidence indicates how certain the model is about its reading; it is separate from risk. Bands: 0–9 no risk, 10–29 informational, 30–49 low, 50–69 medium, 70–89 high, and 90–100 critical. Severity (left badge) is always calculated by IRIS from the risk score. Criticality (right badge, green/yellow/orange/red) is the model's own independent reading of the same scene; it is informational and never replaces severity. Black means that camera has not been analyzed yet.",
          )}
        </p>
      </div>

      <div className="camera-grid-heading">
        <div>
          <h2>{t("Cámaras", "Cameras")}</h2>
          <span>{cameras.length} {t("fuentes configuradas", "configured sources")}</span>
        </div>
        <div className="legend" aria-label={t("Leyenda de estado", "Status legend")}>
          <span><i className="status-dot online" />{t("En línea", "Online")}</span>
          <span><i className="status-dot offline" />{t("Fuera de línea", "Offline")}</span>
          <span><i className="status-dot waiting" />{t("Esperando", "Waiting")}</span>
          <span><i className="status-dot unknown" />{t("Desconocido", "Unknown")}</span>
        </div>
      </div>

      {cameras.length === 0 ? (
        <div className="empty-state">
          <span className="empty-state-mark" aria-hidden="true">
            +
          </span>
          <h2>{t("No hay cámaras configuradas", "No cameras configured")}</h2>
          <p>{t("Un administrador puede agregar la primera fuente RTSP desde Configuración.", "An administrator can add the first RTSP source from Settings.")}</p>
        </div>
      ) : (
        <section className="monitor-camera-grid" aria-label={t("Cámaras monitoreadas", "Monitored cameras")}>
          {cameras.map((camera) => {
            const event = camera.last_event;
            const analysis = event?.analysis;
            const analysisState = analysisStateMeta(camera, t);
            const status = cameraStatusMeta(camera, t);
            const diagnostic = captureDiagnostic(status.kind, camera.poll_interval_seconds, t);
            const severity = analysis?.severity ?? "none";
            const confidence =
              typeof analysis?.confidence === "number"
                ? `${Math.round(analysis.confidence * 100)}%`
                : "—";
            const riskScore =
              typeof analysis?.risk_score === "number"
                ? Math.round(Math.max(0, Math.min(100, analysis.risk_score)))
                : null;
            const needsAttention =
              riskScore !== null
                ? riskScore >= 70
                : Boolean(
                    analysis?.alert ||
                      ALERT_SEVERITIES.has(analysis?.severity?.toLowerCase() ?? ""),
                  );

            return (
              <article
                className={`monitor-camera-card status-${status.kind}`}
                key={camera.camera_id}
              >
                <header className="camera-card-header">
                  <div>
                    <h3>{camera.name}</h3>
                    <span>{camera.camera_id}</span>
                  </div>
                  <span className={`camera-status ${status.kind}`}>
                    <i className={`status-dot ${status.kind}`} />
                    {status.label}
                  </span>
                </header>

                <div className="monitor-camera-media">
                  <DashboardCapture
                    cameraName={camera.name}
                    captureUrl={camera.latest_capture_url}
                    refreshKey={event?.event_id ?? event?.id ?? String(dashboard.revision)}
                    emptyMessage={diagnostic}
                  />
                  <div className="capture-overlay">
                    <span>
                      {camera.latest_capture_at
                        ? relativeTime(camera.latest_capture_at, now, t)
                        : t("sin capturas", "no captures")}
                    </span>
                    <span>
                      {dashboard.settings.frame_width} × {dashboard.settings.frame_height} ·{" "}
                      {camera.poll_interval_seconds}s
                    </span>
                  </div>
                </div>

                <div className="camera-card-body">
                  <div className="analysis-heading">
                    <div>
                      <span className="analysis-kicker">
                        {t("ÚLTIMO ANÁLISIS", "LATEST ANALYSIS")} · {analysisState.label}
                      </span>
                      <strong>
                        {analysis?.event
                          ? analysisEventLabel(analysis.event, language)
                          : t("Sin análisis todavía", "No analysis yet")}
                      </strong>
                    </div>
                    <div className="badge-group">
                      <SeverityBadge severity={severity} />
                      <CriticalityBadge criticidad={analysis?.criticidad} />
                    </div>
                  </div>

                  {analysisState.note && (
                    <p className={`analysis-state-note ${camera.latest_analysis_status}`}>
                      {analysisState.note}
                    </p>
                  )}

                  <p className="analysis-summary">
                    {analysis?.summary
                      ? analysisMessageLabel(analysis.summary, language)
                      :
                      (camera.latest_capture_url
                        ? t("La cámara ya entregó una imagen, pero todavía no hay un análisis disponible.", "The camera has delivered an image, but no analysis is available yet.")
                        : diagnostic)}
                  </p>

                  <dl className="camera-facts">
                    <div>
                      <dt>{t("Riesgo", "Risk")}</dt>
                      <dd>{riskScore === null ? "—" : `${riskScore} / 100`}</dd>
                    </div>
                    <div>
                      <dt>{t("Lectura válida", "Valid reading")}</dt>
                      <dd>{formatClock(event?.captured_at ?? null, locale, t)}</dd>
                    </div>
                    <div>
                      <dt>{t("Confianza IA", "AI confidence")}</dt>
                      <dd>{confidence}</dd>
                    </div>
                  </dl>

                  {analysis?.recommended_action && (
                    <div
                      className={`recommended-action ${needsAttention ? "needs-attention" : ""}`}
                    >
                      <span aria-hidden="true">{needsAttention ? "!" : "→"}</span>
                      <p>{analysisMessageLabel(analysis.recommended_action, language)}</p>
                    </div>
                  )}
                </div>
              </article>
            );
          })}
        </section>
      )}
    </div>
  );
}
