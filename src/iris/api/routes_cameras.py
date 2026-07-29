from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

from iris.config import ConfigurationError, load_config

from .security import CurrentUser

router = APIRouter()

# El navegador nunca debe cachear este archivo: se sobrescribe en cada ciclo
# de análisis (ver CaptureStore.save_latest), así que una respuesta cacheada
# quedaría obsoleta de inmediato.
_NO_STORE_HEADERS = {"Cache-Control": "no-store"}
_EVENT_ID = re.compile(r"^[A-Za-z0-9_-]{8,80}$")


def _camera_capture_dir(camera_id: str, request: Request):
    try:
        config = load_config(config_db_path=request.app.state.users_db_path)
    except ConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if not any(camera.identifier == camera_id for camera in config.cameras):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La cámara no está configurada.",
        )
    capture_dir = config.capture_dir.resolve()
    return capture_dir, capture_dir / camera_id


@router.get("/{camera_id}/latest-frame")
def latest_frame(
    camera_id: str,
    request: Request,
    user: CurrentUser,
) -> FileResponse:
    """Sirve el último frame capturado para el siguiente análisis de visión.

    Este endpoint es deliberadamente independiente de MongoDB (a diferencia
    de ``/detections/*``, que responde 503 sin ``MONGO_URI``): sólo lee un
    archivo de ``config.capture_dir``, nada más. Muestra la vista operativa
    "qué está viendo IRIS ahora mismo" por cámara -- separada por completo
    del historial de capturas con gating por severidad (``CaptureStore.save``),
    que sigue funcionando exactamente igual que antes.
    """

    capture_dir, camera_dir = _camera_capture_dir(camera_id, request)
    resolved_path = (camera_dir / "latest.jpg").resolve()
    if not resolved_path.is_relative_to(capture_dir):
        # Mismo chequeo de contención que routes_detections.detection_image():
        # fuera del directorio de capturas configurado, podría ser un intento
        # de path traversal; no se sirve. (En la práctica no es alcanzable
        # aquí porque camera_id ya debió calzar exactamente con un
        # identificador de cámara configurado arriba, y FastAPI/Starlette no
        # permite "/" dentro de un segmento {camera_id} por defecto.)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Imagen no encontrada.")
    if not resolved_path.is_file():
        # La cámara existe pero todavía no produjo una captura utilizable
        # desde que arrancó iris-monitor (o el archivo aún no se escribió).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Todavía no hay un frame capturado para esta cámara.",
        )

    return FileResponse(
        resolved_path,
        media_type="image/jpeg",
        headers=_NO_STORE_HEADERS,
    )


@router.get("/{camera_id}/events/{event_id}/frame")
def event_frame(
    camera_id: str,
    event_id: str,
    request: Request,
    user: CurrentUser,
) -> FileResponse:
    """Serve the immutable preview paired with one completed analysis."""

    if not _EVENT_ID.fullmatch(event_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Imagen no encontrada.")
    capture_dir, camera_dir = _camera_capture_dir(camera_id, request)
    resolved_path = (camera_dir / f"preview-{event_id}.jpg").resolve()
    if not resolved_path.is_relative_to(capture_dir) or not resolved_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Imagen no encontrada.")
    return FileResponse(
        resolved_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store", "ETag": f'"{event_id}"'},
    )
