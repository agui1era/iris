import { useEffect, useState } from "react";

import { ApiError, fetchCameraLatestFrameBlob } from "../api/client";

type PreviewStatus = "loading" | "ready" | "no-frame" | "error";

/**
 * Shows the last frame IRIS captured for a camera — the same file
 * `GET /cameras/{camera_id}/latest-frame` serves (see `routes_cameras.py`),
 * NOT a live video stream. Loads the blob via `fetchCameraLatestFrameBlob`
 * and renders it through an object URL, same pattern (and same cleanup:
 * revoke on unmount/refetch) as `DetectionThumbnail`.
 *
 * A 404 means the camera simply hasn't completed a capture cycle yet
 * (brand-new camera, or its RTSP source is currently unreachable) — that is
 * a normal, expected state, so it renders a neutral placeholder rather than
 * the error banner used for anything else.
 *
 * Refresh is manual only (button below), deliberately with no
 * polling/timer, mirroring the "Actualizar" button on the Latest
 * detections page (`LatestPage.tsx`).
 */
interface CameraLivePreviewProps {
  cameraId: string;
  pollIntervalSeconds: number;
}

export function CameraLivePreview({
  cameraId,
  pollIntervalSeconds,
}: CameraLivePreviewProps) {
  const [status, setStatus] = useState<PreviewStatus>("loading");
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let createdUrl: string | null = null;
    setStatus("loading");
    setErrorMessage(null);
    setObjectUrl(null);

    fetchCameraLatestFrameBlob(cameraId)
      .then((blob) => {
        if (cancelled) return;
        createdUrl = URL.createObjectURL(blob);
        setObjectUrl(createdUrl);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          // Todavía no hay un frame capturado -- estado normal, no un error.
          setStatus("no-frame");
        } else {
          setErrorMessage(
            err instanceof ApiError ? err.message : "No se pudo cargar la vista de la cámara.",
          );
          setStatus("error");
        }
      });

    return () => {
      cancelled = true;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
    // `refreshToken` has no meaning of its own: bumping it is just how the
    // "Actualizar vista" button re-triggers this same effect on demand.
  }, [cameraId, refreshToken]);

  const handleRefresh = () => setRefreshToken((token) => token + 1);

  return (
    <div className="camera-preview">
      {status === "ready" && objectUrl ? (
        <img
          className="camera-preview-frame thumb"
          src={objectUrl}
          alt={`Último frame capturado de la cámara ${cameraId}`}
        />
      ) : status === "no-frame" ? (
        <div
          className="camera-preview-frame camera-preview-message thumb-empty"
          aria-label="Todavía no hay un frame capturado para esta cámara"
        >
          <strong>Sin frame todavía</strong>
          <small>
            Espera al menos {pollIntervalSeconds}s. Si persiste, revisa la URL RTSP, sus
            credenciales y la red.
          </small>
        </div>
      ) : status === "error" ? (
        <div
          className="camera-preview-frame camera-preview-message thumb-empty"
          role="alert"
        >
          <strong>Error de captura</strong>
          <small>{errorMessage}</small>
        </div>
      ) : (
        <div className="camera-preview-frame thumb-loading" aria-hidden="true" />
      )}

      <button
        type="button"
        className="btn btn-ghost btn-block camera-preview-refresh"
        onClick={handleRefresh}
        disabled={status === "loading"}
      >
        {status === "loading" ? "Actualizando…" : "Actualizar vista"}
      </button>
    </div>
  );
}
