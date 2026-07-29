import { useEffect, useState } from "react";

import { fetchDetectionImageBlob } from "../api/client";

/**
 * Loads a detection's image as an authenticated blob and renders it via an
 * object URL. Plain `<img src="/detections/{id}/image">` can't send an
 * Authorization header, so this is the only way to display it.
 */
export function DetectionThumbnail({ id, alt }: { id: string; alt: string }) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let createdUrl: string | null = null;
    setFailed(false);
    setObjectUrl(null);

    fetchDetectionImageBlob(id)
      .then((blob) => {
        if (cancelled) return;
        createdUrl = URL.createObjectURL(blob);
        setObjectUrl(createdUrl);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });

    return () => {
      cancelled = true;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [id]);

  if (failed) {
    return (
      <div className="thumb thumb-empty" aria-label="Imagen no disponible">
        Sin imagen
      </div>
    );
  }
  if (!objectUrl) {
    return <div className="thumb thumb-loading" aria-hidden="true" />;
  }
  return <img className="thumb" src={objectUrl} alt={alt} />;
}
