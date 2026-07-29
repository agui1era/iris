import { useEffect, useState } from "react";

import { ApiError, fetchDashboardCaptureBlob } from "../api/client";

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
        alt={`Última captura de ${cameraName}`}
      />
    );
  }

  if (state === "loading") {
    return (
      <div className="monitor-capture capture-loading" aria-label={`Cargando captura de ${cameraName}`}>
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
          ? `No se pudo cargar la captura de ${cameraName}`
          : `Todavía no hay captura para ${cameraName}`
      }
    >
      <span className="capture-placeholder-mark" aria-hidden="true">
        ◉
      </span>
      <strong>{state === "error" ? "Captura no disponible" : "Sin captura todavía"}</strong>
      <span>
        {state === "error"
          ? "No se pudo descargar la última imagen capturada."
          : (emptyMessage ?? "Esperando la primera captura de la cámara.")}
      </span>
    </div>
  );
}
