from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .security import CurrentUser

router = APIRouter()

_MAX_LATEST_LIMIT = 200
_MAX_PAGE_SIZE = 200


def get_detections_collection(request: Request) -> Any:
    """Dependencia de FastAPI: la colección Mongo de detecciones configurada.

    Las pruebas la reemplazan vía ``app.dependency_overrides`` con un fake en
    memoria; en producción resuelve a la colección construida en
    ``create_app()`` a partir de ``config.mongo_uri``.
    """

    collection = getattr(request.app.state, "detections_collection", None)
    if collection is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MongoDB no está configurado.",
        )
    return collection


DetectionsCollection = Annotated[Any, Depends(get_detections_collection)]


def _project_document(document: dict[str, Any]) -> dict[str, Any]:
    analysis = document.get("analysis")
    analysis = analysis if isinstance(analysis, dict) else {}
    return {
        "id": str(document.get("_id")),
        "event_type": document.get("event_type"),
        "camera_id": document.get("camera_id"),
        "camera_name": document.get("camera_name"),
        "captured_at": document.get("captured_at"),
        "completed_at": document.get("completed_at"),
        "trigger": document.get("trigger"),
        "risk_score": analysis.get("risk_score"),
        "severity": analysis.get("severity"),
        "alert": analysis.get("alert"),
        "event": analysis.get("event"),
        "summary": analysis.get("summary"),
        "confidence": analysis.get("confidence"),
        "recommended_action": analysis.get("recommended_action"),
        "has_image": bool(document.get("snapshot_path")),
    }


class DetectionsPage(BaseModel):
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


@router.get("/latest")
def latest_detections(
    collection: DetectionsCollection,
    user: CurrentUser,
    limit: int = Query(default=20, ge=1),
) -> list[dict[str, Any]]:
    capped_limit = min(limit, _MAX_LATEST_LIMIT)
    cursor = (
        collection.find({"event_type": "analysis.completed"})
        .sort("captured_at", -1)
        .limit(capped_limit)
    )
    return [_project_document(document) for document in cursor]


@router.get("", response_model=DetectionsPage)
def list_detections(
    collection: DetectionsCollection,
    user: CurrentUser,
    date_from: str | None = None,
    date_to: str | None = None,
    camera_id: str | None = None,
    severity: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1),
) -> DetectionsPage:
    capped_page_size = min(page_size, _MAX_PAGE_SIZE)

    query: dict[str, Any] = {"event_type": "analysis.completed"}
    if camera_id:
        query["camera_id"] = camera_id
    if severity:
        query["analysis.severity"] = severity
    captured_range: dict[str, Any] = {}
    if date_from:
        captured_range["$gte"] = date_from
    if date_to:
        captured_range["$lte"] = date_to
    if captured_range:
        query["captured_at"] = captured_range

    total = collection.count_documents(query)
    skip = (page - 1) * capped_page_size
    cursor = collection.find(query).sort("captured_at", -1).skip(skip).limit(capped_page_size)
    items = [_project_document(document) for document in cursor]
    return DetectionsPage(items=items, total=total, page=page, page_size=capped_page_size)


@router.get("/{detection_id}/image")
def detection_image(
    detection_id: str,
    request: Request,
    collection: DetectionsCollection,
    user: CurrentUser,
) -> FileResponse:
    try:
        object_id = ObjectId(detection_id)
    except (InvalidId, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Detección no encontrada."
        ) from exc

    document = collection.find_one({"_id": object_id})
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Detección no encontrada."
        )

    snapshot_path = document.get("snapshot_path")
    if not snapshot_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La detección no tiene una imagen asociada.",
        )

    capture_dir = request.app.state.config.capture_dir.resolve()
    resolved_path = Path(snapshot_path).resolve()
    if not resolved_path.is_relative_to(capture_dir):
        # Fuera del directorio de capturas configurado: podría ser un intento
        # de path traversal (snapshot_path con "../"), no se sirve.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Imagen no encontrada.")
    if not resolved_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Imagen no encontrada.")

    return FileResponse(resolved_path, media_type="image/jpeg")
