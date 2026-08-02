import { useEffect, useState } from "react";

import { ApiError, fetchDashboardCaptureBlob } from "../api/client";
import { useLanguage } from "../i18n/useLanguage";

type CaptureState = "loading" | "ready" | "empty" | "error";

interface DashboardCaptureProps {
  cameraName: string;
  captureUrl: string | null;
  refreshKey: string;
  emptyMessage?: string;
}

export function DashboardCapture({
  cameraName,
  captureUrl,
  refreshKey,
  emptyMessage,
}: DashboardCaptureProps) {
  const { t } = useLanguage();
  const [state, setState] = useState<CaptureState>(captureUrl ? "loading" : "empty");
  const [objectUrl, setObjectUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let createdUrl: string | null = null;
    setObjectUrl(null);

    if (!captureUrl) {
      setState("empty");
      return () => undefined;
    }

    setState("loading");
    fetchDashboardCaptureBlob(captureUrl)
      .then((blob) => {
        if (cancelled) return;
        createdUrl = URL.createObjectURL(blob);
        setObjectUrl(createdUrl);
        setState("ready");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setState(error instanceof ApiError && error.status === 404 ? "empty" : "error");
      });

    return () => {
      cancelled = true;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [captureUrl, refreshKey]);

  if (state === "ready" && objectUrl) {
    return (
      <img
        className="monitor-capture"
        src={objectUrl}
        alt={t(`Última captura de ${cameraName}`, `Latest capture from ${cameraName}`)}
      />
    );
  }

  if (state === "loading") {
    return (
      <div className="monitor-capture capture-loading" aria-label={t(`Cargando captura de ${cameraName}`, `Loading capture from ${cameraName}`)}>
        <span aria-hidden="true" />
      </div>
    );
  }

  return (
    <div
      className="monitor-capture capture-empty"
      role={state === "error" ? "alert" : "img"}
      aria-label={
        state === "error"
          ? t(`No se pudo cargar la captura de ${cameraName}`, `Could not load the capture from ${cameraName}`)
          : t(`Todavía no hay captura para ${cameraName}`, `There is no capture for ${cameraName} yet`)
      }
    >
      <span className="capture-placeholder-mark" aria-hidden="true">
        ◉
      </span>
      <strong>{state === "error" ? t("Captura no disponible", "Capture unavailable") : t("Sin captura todavía", "No capture yet")}</strong>
      <span>
        {state === "error"
          ? t("No se pudo descargar la última imagen capturada.", "The latest captured image could not be downloaded.")
          : (emptyMessage ?? t("Esperando la primera captura de la cámara.", "Waiting for the camera's first capture."))}
      </span>
    </div>
  );
}
