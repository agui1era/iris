from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from pymongo.errors import PyMongoError

from iris import config_store
from iris.config import ConfigurationError, load_config
from iris.models import ServiceConfig

from .security import CurrentUser

router = APIRouter()
logger = logging.getLogger(__name__)

_RTSP_TEXT = re.compile(r"(?i)rtsps?://[^\s<>'\"]+")
_CAPTURE_FRESHNESS_MAX_SECONDS = 300.0
_CONNECTIVITY_FRESHNESS_SECONDS = 90.0
_ANALYSIS_FIELDS = (
    "risk_score",
    "severity",
    "alert",
    "event",
    "summary",
    "confidence",
    "observations",
    "recommended_action",
    "requires_human_review",
    "criticidad",
)


class DashboardSettingsResponse(BaseModel):
    frame_width: int
    frame_height: int
    max_api_calls_per_minute: int


class DashboardEventResponse(BaseModel):
    id: str
    event_id: str | None
    event_type: str | None
    captured_at: str | None
    completed_at: str | None
    trigger: str | None
    analysis: dict[str, Any] | None
    created_at: str | None


class DashboardCameraResponse(BaseModel):
    camera_id: str
    index: int
    name: str
    poll_interval_seconds: float
    status: Literal["online", "offline", "waiting", "unknown"]
    last_event: DashboardEventResponse | None
    latest_capture_url: str | None
    latest_capture_at: str | None
    latest_analysis_status: Literal["completed", "failed", "pending", "none", "unavailable"]
    latest_analysis_at: str | None


class DashboardResponse(BaseModel):
    revision: int
    settings: DashboardSettingsResponse
    cameras: list[DashboardCameraResponse]


def get_dashboard_detections_collection(request: Request) -> Any | None:
    """Return the existing Mongo collection, or ``None`` when Mongo is disabled.

    Dashboard configuration and latest-frame previews do not require MongoDB.
    Keeping this dependency optional lets a new installation reach the
    operational view before it enables detection history, while tests can
    replace it with an in-memory collection.
    """

    return getattr(request.app.state, "detections_collection", None)


DashboardDetectionsCollection = Annotated[
    Any | None,
    Depends(get_dashboard_detections_collection),
]


def _redact_rtsp(value: Any) -> Any:
    """Recursively remove complete RTSP URLs from public, model-controlled text."""

    if isinstance(value, str):
        return _RTSP_TEXT.sub("<rtsp-redacted>", value)
    if isinstance(value, dict):
        return {str(key): _redact_rtsp(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_rtsp(item) for item in value]
    return value


def _as_public_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(_redact_rtsp(str(value)))


def _latest_analysis_document(
    collection: Any,
    camera_id: str,
) -> dict[str, Any] | None:
    cursor = (
        collection.find(
            {
                "camera_id": camera_id,
                "event_type": "analysis.completed",
            }
        )
        .sort("captured_at", -1)
        .limit(1)
    )
    return next(iter(cursor), None)


def _latest_attempt_document(
    collection: Any,
    camera_id: str,
) -> dict[str, Any] | None:
    cursor = (
        collection.find(
            {
                "camera_id": camera_id,
                # analysis.skipped is a deliberate no-op (variation gating), not a
                # real attempt result, but it still needs to count as the most
                # recent "attempt" so a skipped cycle isn't shown as PROCESANDO.
                "event_type": {
                    "$in": ["analysis.completed", "analysis.failed", "analysis.skipped"]
                },
            }
        )
        .sort("captured_at", -1)
        .limit(1)
    )
    return next(iter(cursor), None)


def _latest_connectivity_document(
    collection: Any,
    camera_id: str,
) -> dict[str, Any] | None:
    """Read connectivity separately so it never replaces the semantic message."""

    try:
        cursor = (
            collection.find(
                {
                    "camera_id": camera_id,
                    "event_type": {
                        "$in": ["camera.connected", "camera.offline"],
                    },
                }
            )
            .sort("observed_at", -1)
            .limit(1)
        )
        return next(iter(cursor), None)
    except (AttributeError, NotImplementedError, TypeError):
        # Some lightweight collection adapters only implement simple equality
        # filters. The semantic analysis remains useful; connectivity is
        # explicitly unknown rather than guessed from analysis age.
        return None


def _project_event(document: dict[str, Any] | None) -> DashboardEventResponse | None:
    if document is None:
        return None
    raw_analysis = document.get("analysis")
    if isinstance(raw_analysis, dict):
        analysis = {
            field_name: _redact_rtsp(raw_analysis[field_name])
            for field_name in _ANALYSIS_FIELDS
            if field_name in raw_analysis
        }
    else:
        analysis = None
    event_id = _as_public_string(document.get("event_id"))
    return DashboardEventResponse(
        id=event_id or str(document.get("_id", "")),
        event_id=event_id,
        event_type=_as_public_string(document.get("event_type")),
        captured_at=_as_public_string(document.get("captured_at")),
        completed_at=_as_public_string(document.get("completed_at")),
        trigger=_as_public_string(document.get("trigger")),
        analysis=analysis,
        created_at=_as_public_string(document.get("received_at")),
    )


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _camera_status(
    analysis: DashboardEventResponse | None,
    connectivity: dict[str, Any] | None,
    *,
    latest_capture_at: str | None,
    poll_interval_seconds: float,
) -> Literal["online", "offline", "waiting", "unknown"]:
    captured_at = _parse_datetime(latest_capture_at)
    observed_at = (
        _parse_datetime(connectivity.get("observed_at")) if connectivity is not None else None
    )
    event_type = connectivity.get("event_type") if connectivity is not None else None

    # An explicit offline transition wins unless a newer operational frame
    # proves that the reader recovered after that event.
    if event_type == "camera.offline" and (
        captured_at is None or observed_at is None or observed_at >= captured_at
    ):
        return "offline"

    now = datetime.now(UTC)
    freshness_window = max(
        60.0,
        min(_CAPTURE_FRESHNESS_MAX_SECONDS, poll_interval_seconds * 2.5),
    )
    if captured_at is not None and (now - captured_at).total_seconds() <= freshness_window:
        return "online"

    # During RTSP warm-up there may be a connection event before the first
    # latest.jpg. Treat only a recent transition as online; never keep a camera
    # green forever from one historical "connected" row.
    if (
        event_type == "camera.connected"
        and observed_at is not None
        and (now - observed_at).total_seconds() <= _CONNECTIVITY_FRESHNESS_SECONDS
    ):
        return "online"
    return "waiting" if analysis is None and captured_at is None else "unknown"


def _latest_analysis_state(
    attempt: dict[str, Any] | None,
    *,
    latest_capture_at: str | None,
    history_available: bool,
) -> tuple[
    Literal["completed", "failed", "pending", "none", "unavailable"],
    str | None,
]:
    if not history_available:
        return "unavailable", None
    if attempt is None:
        return ("pending" if latest_capture_at is not None else "none"), None

    attempt_at = (
        _parse_datetime(attempt.get("completed_at"))
        or _parse_datetime(attempt.get("received_at"))
        or _parse_datetime(attempt.get("captured_at"))
    )
    capture_at = _parse_datetime(latest_capture_at)
    if capture_at is not None and attempt_at is not None and capture_at > attempt_at:
        return "pending", attempt_at.isoformat()

    event_type = attempt.get("event_type")
    if event_type == "analysis.failed":
        return "failed", attempt_at.isoformat() if attempt_at is not None else None
    if event_type in ("analysis.completed", "analysis.skipped"):
        # A skip means IRIS deliberately chose not to call Alibaba (the scene
        # was calm and unchanged): that's a settled, up-to-date state from the
        # dashboard's point of view, not something still "processing".
        return "completed", attempt_at.isoformat() if attempt_at is not None else None
    return "none", attempt_at.isoformat() if attempt_at is not None else None


def _latest_capture(
    config: ServiceConfig,
    camera_id: str,
    event_id: str | None,
    event_captured_at: str | None,
) -> tuple[str | None, str | None]:
    # La tarjeta principal es operacional: si existe un frame recién enviado
    # debe mostrarlo aunque Alibaba haya fallado después del último evento
    # completado. El historial conserva el preview inmutable por event_id.
    capture_dir = config.capture_dir.resolve()
    candidate = (capture_dir / camera_id / "latest.jpg").resolve()
    if candidate.is_relative_to(capture_dir) and candidate.is_file():
        # routes_cameras.latest_frame repite la validación de cámara y
        # contención antes de servir el JPEG con no-store. El mtime cambia la
        # URL operativa en cada os.replace para que React vuelva a descargarla
        # aunque el event_id no cambie porque Alibaba falló.
        try:
            stat = candidate.stat()
        except OSError:
            pass
        else:
            captured_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
            url = (
                f"/cameras/{quote(camera_id, safe='')}/latest-frame"
                f"?v={stat.st_mtime_ns}"
            )
            return url, captured_at
    if event_id:
        # Fallback para datos históricos creados antes de que latest.jpg
        # existiera o cuando el directorio operacional se perdió.
        url = f"/cameras/{quote(camera_id, safe='')}/events/{quote(event_id, safe='')}/frame"
        return url, event_captured_at
    return None, None


def _fresh_config(
    request: Request,
) -> tuple[ServiceConfig, int]:
    db_path: Path = request.app.state.users_db_path
    try:
        mapping, revision = config_store.read_config_snapshot(db_path)
        # A users-only database can exist even when runtime configuration
        # still comes from .env. In that case the app's startup snapshot is
        # the only complete validated configuration available.
        if mapping:
            # SQLite is authoritative for dynamic values, while deployment
            # secrets remain in the process environment and are never copied
            # into the dashboard response or required to live in SQLite.
            source = dict(os.environ)
            source.update(mapping)
            config = load_config(env=source)
        else:
            config = request.app.state.config
    except (ConfigurationError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"La configuración operativa no está disponible: {exc}",
        ) from exc
    return config, revision


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    request: Request,
    collection: DashboardDetectionsCollection,
    user: CurrentUser,
) -> DashboardResponse:
    """Return one safe operational card per configured camera.

    RTSP URLs and per-camera prompts are intentionally absent. Mongo documents
    are projected through an allow-list instead of being returned verbatim.
    """

    config, revision = _fresh_config(request)
    cameras: list[DashboardCameraResponse] = []
    mongo_available = collection is not None
    for camera in config.cameras:
        analysis_document = None
        attempt_document = None
        connectivity_document = None
        history_available = mongo_available
        if mongo_available:
            try:
                analysis_document = _latest_analysis_document(collection, camera.identifier)
                attempt_document = _latest_attempt_document(collection, camera.identifier)
                connectivity_document = _latest_connectivity_document(
                    collection,
                    camera.identifier,
                )
            except PyMongoError:
                # Mongo is history, not the camera data plane. A database outage
                # must not hide latest.jpg or make the operational dashboard 503.
                logger.warning(
                    "Mongo no está disponible; el dashboard continuará sólo con capturas."
                )
                mongo_available = False
                history_available = False

        event = _project_event(analysis_document)
        capture_url, capture_at = _latest_capture(
            config,
            camera.identifier,
            event.event_id if event is not None else None,
            event.captured_at if event is not None else None,
        )
        analysis_status, analysis_at = _latest_analysis_state(
            attempt_document,
            latest_capture_at=capture_at,
            history_available=history_available,
        )
        cameras.append(
            DashboardCameraResponse(
                camera_id=camera.identifier,
                index=camera.index,
                name=str(_redact_rtsp(camera.name)),
                poll_interval_seconds=camera.poll_interval_seconds,
                status=_camera_status(
                    event,
                    connectivity_document,
                    latest_capture_at=capture_at,
                    poll_interval_seconds=camera.poll_interval_seconds,
                ),
                last_event=event,
                latest_capture_url=capture_url,
                latest_capture_at=capture_at,
                latest_analysis_status=analysis_status,
                latest_analysis_at=analysis_at,
            )
        )

    settings = DashboardSettingsResponse(
        frame_width=config.frame_width,
        frame_height=config.frame_height,
        max_api_calls_per_minute=config.max_api_calls_per_minute,
    )
    return DashboardResponse(revision=revision, settings=settings, cameras=cameras)
