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

const UI_POLL_INTERVAL_MS = 3_000;
const ALERT_SEVERITIES = new Set(["high", "critical"]);

function formatClock(value: string | null): string {
  if (!value) return "Sin registro";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Hora desconocida";
  return new Intl.DateTimeFormat("es-CL", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function relativeTime(value: string | null, now: number): string {
  if (!value) return "sin actividad";
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return "hora desconocida";
  const seconds = Math.max(0, Math.round((now - timestamp) / 1_000));
  if (seconds < 10) return "ahora";
  if (seconds < 60) return `hace ${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `hace ${minutes} min`;
  return `hace ${Math.floor(minutes / 60)} h`;
}

function isCameraOnline(camera: DashboardCamera): boolean {
  return camera.status.toLowerCase() === "online";
}

function cameraStatusMeta(camera: DashboardCamera): {
  kind: "online" | "offline" | "waiting" | "unknown";
  label: string;
} {
  const normalized = camera.status.toLowerCase();
  if (normalized === "online") return { kind: "online", label: "En línea" };
  if (normalized === "offline") return { kind: "offline", label: "Fuera de línea" };
  if (normalized === "waiting") return { kind: "waiting", label: "Esperando señal" };
  return { kind: "unknown", label: "Estado desconocido" };
}

function captureDiagnostic(
  status: "online" | "offline" | "waiting" | "unknown",
  pollIntervalSeconds: number,
): string {
  if (status === "offline") {
    return "Sin conexión RTSP. Revisa URL, credenciales y acceso de red.";
  }
  if (status === "waiting") {
    return `Esperando la primera conexión; una captura puede tardar hasta ${pollIntervalSeconds} s.`;
  }
  if (status === "unknown") {
    return "Sin estado de conectividad reciente. Revisa el stream si no aparece una captura.";
  }
  return `Cámara conectada; esperando el próximo análisis (polling cada ${pollIntervalSeconds} s).`;
}

function analysisStateMeta(camera: DashboardCamera): {
  label: string;
  note: string | null;
} {
  if (camera.latest_analysis_status === "failed") {
    return {
      label: "ÚLTIMO INTENTO FALLÓ",
      note: camera.last_event
        ? "Alibaba falló en el último intento; se conserva abajo la última lectura válida."
        : "Alibaba falló en el último intento y todavía no existe una lectura válida.",
    };
  }
  if (camera.latest_analysis_status === "pending") {
    return {
      label: "PROCESANDO",
      note: camera.last_event
        ? "Hay una captura más reciente en proceso; la lectura visible corresponde al último análisis terminado."
        : "La primera captura está esperando o siendo procesada por Alibaba.",
    };
  }
  if (camera.latest_analysis_status === "unavailable") {
    return {
      label: "HISTORIAL NO DISPONIBLE",
      note: "La captura sigue operativa, pero no se pudo consultar el estado semántico.",
    };
  }
  if (camera.latest_analysis_status === "completed") {
    return { label: "COMPLETADO", note: null };
  }
  return { label: "SIN LECTURAS", note: null };
}

export function MonitoringPage() {
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
          : "No se pudo conectar con el servicio de monitoreo.";
      setError(message);
    } finally {
      requestInFlightRef.current = false;
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

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
            <span className="eyebrow">OPERACIÓN EN TIEMPO REAL</span>
            <h1>Centro de monitoreo</h1>
          </div>
        </div>
        <div className="monitor-skeleton-grid" aria-label="Cargando cámaras">
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
          <h1>Monitoreo no disponible</h1>
          <p>{error ?? "El servicio no respondió."}</p>
          <button type="button" className="btn btn-primary" onClick={() => void load(true)}>
            Reintentar conexión
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
          <span className="eyebrow">OPERACIÓN EN TIEMPO REAL</span>
          <h1>Centro de monitoreo</h1>
          <p>Capturas relevantes, riesgo operacional y lectura semántica de Alibaba.</p>
        </div>
        <div className="monitor-refresh">
          <span className="refresh-copy" aria-live="polite">
            {updatedAt ? `Sincronizado ${formatClock(updatedAt.toISOString())}` : "Sin sincronizar"}
          </span>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => void load(true)}
            disabled={refreshing}
          >
            {refreshing ? "Sincronizando…" : "Actualizar ahora"}
          </button>
        </div>
      </div>

      {error && (
        <div className="alert alert-warning" role="alert">
          Se perdió la última sincronización: {error}. Se mantienen los últimos datos recibidos.
        </div>
      )}

      <section className="monitor-metrics" aria-label="Resumen del monitoreo">
        <div className="metric-card">
          <span className="metric-label">Cámaras activas</span>
          <strong>
            {metrics.online}
            <small> / {cameras.length}</small>
          </strong>
          <span className="metric-foot positive">● señal reciente</span>
        </div>
        <div className="metric-card">
          <span className="metric-label">Alertas actuales</span>
          <strong>{metrics.alerts}</strong>
          <span className={metrics.alerts > 0 ? "metric-foot warning" : "metric-foot muted"}>
            {metrics.alerts > 0 ? "requieren atención" : "sin alertas críticas"}
          </span>
        </div>
        <div className="metric-card">
          <span className="metric-label">Riesgo promedio</span>
          <strong>{metrics.averageRisk === null ? "—" : Math.round(metrics.averageRisk)}</strong>
          <span className="metric-foot muted">riesgo promedio / 100</span>
        </div>
        <div className="metric-card">
          <span className="metric-label">Polling por cámara</span>
          <strong>
            {metrics.pollingRange}
            <small> s</small>
          </strong>
          <span className="metric-foot muted">mínimo 10 s · interfaz cada 3 s</span>
        </div>
      </section>

      <div className="score-explainer">
        <span aria-hidden="true">i</span>
        <p>
          <strong>Risk score</strong> mide urgencia operacional de 0 a 100.
          <strong> Confianza</strong> indica cuán seguro está el modelo de su lectura; es una medida
          separada y no equivale a riesgo. Bandas: 0–9 sin riesgo, 10–29 informativa, 30–49 baja,
          50–69 media, 70–89 alta y 90–100 crítica.
          <strong> Severidad</strong> (badge izquierdo) la calcula IRIS siempre a partir del risk
          score. <strong>Criticidad</strong> (badge derecho, verde/amarillo/naranja/rojo) es la
          lectura propia e independiente del modelo sobre la misma escena; se muestra a título
          informativo y nunca reemplaza a la severidad. Negro significa que todavía no hay
          análisis para esa cámara.
        </p>
      </div>

      <div className="camera-grid-heading">
        <div>
          <h2>Cámaras</h2>
          <span>{cameras.length} fuentes configuradas</span>
        </div>
        <div className="legend" aria-label="Leyenda de estado">
          <span><i className="status-dot online" />En línea</span>
          <span><i className="status-dot offline" />Fuera de línea</span>
          <span><i className="status-dot waiting" />Esperando</span>
          <span><i className="status-dot unknown" />Desconocido</span>
        </div>
      </div>

      {cameras.length === 0 ? (
        <div className="empty-state">
          <span className="empty-state-mark" aria-hidden="true">
            +
          </span>
          <h2>No hay cámaras configuradas</h2>
          <p>Un administrador puede agregar la primera fuente RTSP desde Configuración.</p>
        </div>
      ) : (
        <section className="monitor-camera-grid" aria-label="Cámaras monitoreadas">
          {cameras.map((camera) => {
            const event = camera.last_event;
            const analysis = event?.analysis;
            const analysisState = analysisStateMeta(camera);
            const status = cameraStatusMeta(camera);
            const diagnostic = captureDiagnostic(status.kind, camera.poll_interval_seconds);
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
                        ? relativeTime(camera.latest_capture_at, now)
                        : "sin capturas"}
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
                        ÚLTIMA LECTURA ALIBABA · {analysisState.label}
                      </span>
                      <strong>{analysis?.event ?? "Sin análisis todavía"}</strong>
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
                    {analysis?.summary ??
                      (camera.latest_capture_url
                        ? "La cámara ya entregó una imagen, pero Alibaba todavía no registra una lectura semántica."
                        : diagnostic)}
                  </p>

                  <dl className="camera-facts">
                    <div>
                      <dt>Riesgo</dt>
                      <dd>{riskScore === null ? "—" : `${riskScore} / 100`}</dd>
                    </div>
                    <div>
                      <dt>Lectura válida</dt>
                      <dd>{formatClock(event?.captured_at ?? null)}</dd>
                    </div>
                    <div>
                      <dt>Confianza IA</dt>
                      <dd>{confidence}</dd>
                    </div>
                  </dl>

                  {analysis?.recommended_action && (
                    <div
                      className={`recommended-action ${needsAttention ? "needs-attention" : ""}`}
                    >
                      <span aria-hidden="true">{needsAttention ? "!" : "→"}</span>
                      <p>{analysis.recommended_action}</p>
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
