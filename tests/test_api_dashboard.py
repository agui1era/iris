from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError

from iris import config_store
from iris.api.routes_dashboard import router
from iris.api.security import create_access_token
from iris.config import load_config
from iris.users_store import create_user

_AUTH_SECRET = "test-jwt-secret-at-least-32-bytes-long"


class FakeCursor:
    def __init__(self, documents: Iterable[dict[str, Any]]) -> None:
        self._documents = list(documents)

    def sort(self, field: str, direction: int) -> FakeCursor:
        self._documents.sort(
            key=lambda document: document.get(field, ""),
            reverse=direction < 0,
        )
        return self

    def limit(self, count: int) -> FakeCursor:
        self._documents = self._documents[:count]
        return self

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self._documents)


class FakeCollection:
    def __init__(self, documents: Iterable[dict[str, Any]]) -> None:
        self._documents = list(documents)

    def find(self, query: dict[str, Any]) -> FakeCursor:
        def matches(document: dict[str, Any]) -> bool:
            for key, expected in query.items():
                actual = document.get(key)
                if isinstance(expected, dict) and "$in" in expected:
                    if actual not in expected["$in"]:
                        return False
                elif actual != expected:
                    return False
            return True

        return FakeCursor(document for document in self._documents if matches(document))


class BrokenCollection:
    def find(self, query: dict[str, Any]) -> FakeCursor:
        raise ServerSelectionTimeoutError("Mongo is unavailable")


def _baseline(capture_dir: Path) -> dict[str, str]:
    return {
        "CAM1_NAME": "Dormitorio",
        "CAM1_RTSP_URL": "rtsp://admin:camera-password@camera-one/live",
        "CAM1_PROMPT": "Vigila caídas visibles.",
        "CAM1_POLL_INTERVAL_SECONDS": "30",
        "CAM3_NAME": "Living",
        "CAM3_RTSP_URL": "rtsp://viewer:other-password@camera-three/live",
        "CAM3_PROMPT": "Vigila inmovilidad.",
        "CAM3_POLL_INTERVAL_SECONDS": "60",
        "POLL_INTERVAL_SECONDS": "30",
        "FRAME_WIDTH": "640",
        "FRAME_HEIGHT": "360",
        "ANALYSIS_COOLDOWN_SECONDS": "45",
        "MAX_API_CALLS_PER_MINUTE": "10",
        "DASHSCOPE_API_KEY": "dashscope-secret",
        "DASHSCOPE_BASE_URL": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "AUTH_JWT_SECRET": _AUTH_SECRET,
        "CAPTURE_DIR": str(capture_dir),
    }


def _client(
    tmp_path: Path,
    documents: Iterable[dict[str, Any]] | None = (),
    *,
    collection: Any | None = None,
) -> tuple[TestClient, dict[str, str], Path]:
    db_path = tmp_path / "config.db"
    capture_dir = tmp_path / "captures"
    mapping = _baseline(capture_dir)
    config_store.write_config_mapping(db_path, mapping)
    config = load_config(config_db_path=db_path)

    app = FastAPI()
    app.state.config = config
    app.state.users_db_path = db_path
    app.state.detections_collection = (
        collection if collection is not None else FakeCollection(documents or ())
    )
    app.include_router(router, prefix="/api")

    create_user(db_path, "viewer", "unused-test-password", "normal")
    token = create_access_token("viewer", "normal", _AUTH_SECRET, 60)
    headers = {"Authorization": f"Bearer {token}"}
    return TestClient(app), headers, capture_dir


def _event(
    camera_id: str,
    captured_at: datetime,
    *,
    event_type: str = "analysis.completed",
    summary: str = "Actividad normal.",
    event_id: str | None = None,
) -> dict[str, Any]:
    document = {
        "_id": ObjectId(),
        "camera_id": camera_id,
        "event_type": event_type,
        "captured_at": captured_at.isoformat(),
        "completed_at": (captured_at + timedelta(seconds=1)).isoformat(),
        "received_at": (captured_at + timedelta(seconds=2)),
        "trigger": "poll",
        "analysis": {
            "risk_score": 35,
            "severity": "low",
            "alert": False,
            "event": "normal_activity",
            "summary": summary,
            "confidence": 0.91,
            "recommended_action": "Continuar monitoreo.",
            "rtsp_url": "rtsp://should:not-leak@hidden/live",
        },
        "snapshot_path": "/private/path/that/must/not/be/exposed.jpg",
    }
    if event_id is not None:
        document["event_id"] = event_id
    return document


def _connectivity_event(
    camera_id: str,
    event_type: str,
    observed_at: datetime,
) -> dict[str, Any]:
    return {
        "_id": ObjectId(),
        "camera_id": camera_id,
        "event_type": event_type,
        "observed_at": observed_at.isoformat(),
    }


def test_dashboard_returns_global_capture_settings_and_latest_event(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    documents = [
        _event("CAM1", now - timedelta(seconds=30), summary="Evento anterior."),
        _event("CAM1", now - timedelta(seconds=2), summary="Persona caminando."),
        _connectivity_event("CAM1", "camera.offline", now - timedelta(minutes=1)),
        _connectivity_event("CAM1", "camera.connected", now - timedelta(seconds=3)),
        _event("CAM99", now, summary="Cámara no configurada."),
    ]
    client, headers, _ = _client(tmp_path, documents)

    response = client.get("/api/dashboard", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["revision"], int)
    assert body["settings"] == {
        "frame_width": 640,
        "frame_height": 360,
        "analysis_cooldown_seconds": 45.0,
        "max_api_calls_per_minute": 10,
    }
    assert [camera["camera_id"] for camera in body["cameras"]] == ["CAM1", "CAM3"]

    camera = body["cameras"][0]
    assert camera["index"] == 1
    assert camera["name"] == "Dormitorio"
    assert "width" not in camera
    assert camera["poll_interval_seconds"] == 30.0
    assert body["cameras"][1]["poll_interval_seconds"] == 60.0
    assert camera["status"] == "online"
    assert camera["latest_analysis_status"] == "completed"
    assert camera["latest_analysis_at"] is not None
    assert camera["last_event"]["analysis"]["summary"] == "Persona caminando."
    assert camera["last_event"]["analysis"]["risk_score"] == 35


def test_dashboard_never_returns_rtsp_urls_prompts_or_unlisted_mongo_fields(
    tmp_path: Path,
) -> None:
    summary = "Se recibió rtsp://analyst:analysis-password@internal/live"
    client, headers, _ = _client(
        tmp_path,
        [_event("CAM1", datetime.now(UTC), summary=summary)],
    )

    response = client.get("/api/dashboard", headers=headers)

    assert response.status_code == 200
    body = response.json()
    serialized = response.text
    assert "camera-password" not in serialized
    assert "other-password" not in serialized
    assert "analysis-password" not in serialized
    assert "dashscope-secret" not in serialized
    assert "that/must/not/be/exposed" not in serialized
    for camera in body["cameras"]:
        assert "rtsp_url" not in camera
        assert "prompt" not in camera
    assert "rtsp_url" not in body["cameras"][0]["last_event"]["analysis"]
    assert body["cameras"][0]["last_event"]["analysis"]["summary"] == "Se recibió <rtsp-redacted>"


def test_dashboard_is_available_without_mongo_and_marks_cameras_waiting(
    tmp_path: Path,
) -> None:
    client, headers, _ = _client(tmp_path, collection=None, documents=None)
    client.app.state.detections_collection = None

    response = client.get("/api/dashboard", headers=headers)

    assert response.status_code == 200
    assert all(camera["last_event"] is None for camera in response.json()["cameras"])
    assert all(camera["status"] == "waiting" for camera in response.json()["cameras"])
    assert all(
        camera["latest_analysis_status"] == "unavailable"
        for camera in response.json()["cameras"]
    )


def test_dashboard_exposes_only_existing_safe_latest_frame_url(
    tmp_path: Path,
) -> None:
    client, headers, capture_dir = _client(tmp_path)
    camera_dir = capture_dir / "CAM1"
    camera_dir.mkdir(parents=True)
    (camera_dir / "latest.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    response = client.get("/api/dashboard", headers=headers)

    assert response.status_code == 200
    cameras = {camera["camera_id"]: camera for camera in response.json()["cameras"]}
    assert cameras["CAM1"]["latest_capture_url"].startswith(
        "/cameras/CAM1/latest-frame?v="
    )
    assert cameras["CAM1"]["latest_capture_at"] is not None
    assert cameras["CAM1"]["latest_analysis_status"] == "pending"
    assert cameras["CAM3"]["latest_capture_url"] is None
    assert cameras["CAM3"]["latest_capture_at"] is None
    assert cameras["CAM3"]["latest_analysis_status"] == "none"


def test_dashboard_prefers_versioned_event_frame_and_public_event_id(
    tmp_path: Path,
) -> None:
    event_id = "832e8c5a-7f6c-4bf9-b106-6a387928fa28"
    client, headers, _ = _client(
        tmp_path,
        [_event("CAM1", datetime.now(UTC), event_id=event_id)],
    )

    response = client.get("/api/dashboard", headers=headers)

    assert response.status_code == 200
    camera = response.json()["cameras"][0]
    assert camera["last_event"]["id"] == event_id
    assert camera["last_event"]["event_id"] == event_id
    assert camera["latest_capture_url"] == f"/cameras/CAM1/events/{event_id}/frame"
    assert camera["latest_capture_at"] == camera["last_event"]["captured_at"]


def test_dashboard_prefers_operational_latest_even_when_last_event_is_older(
    tmp_path: Path,
) -> None:
    event_id = "832e8c5a-7f6c-4bf9-b106-6a387928fa28"
    client, headers, capture_dir = _client(
        tmp_path,
        [_event("CAM1", datetime.now(UTC) - timedelta(minutes=1), event_id=event_id)],
    )
    camera_dir = capture_dir / "CAM1"
    camera_dir.mkdir(parents=True)
    (camera_dir / "latest.jpg").write_bytes(b"\xff\xd8new-frame\xff\xd9")

    response = client.get("/api/dashboard", headers=headers)

    assert response.status_code == 200
    camera = response.json()["cameras"][0]
    assert camera["last_event"]["event_id"] == event_id
    assert camera["latest_capture_url"].startswith("/cameras/CAM1/latest-frame?v=")
    assert camera["latest_capture_at"] != camera["last_event"]["captured_at"]


def test_dashboard_failure_never_replaces_latest_completed_analysis(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    client, headers, _ = _client(
        tmp_path,
        [
            _event("CAM1", now - timedelta(seconds=5), summary="Último análisis válido."),
            _event(
                "CAM1",
                now,
                event_type="analysis.failed",
                summary="Este documento no debe reemplazar el análisis.",
            ),
        ],
    )

    response = client.get("/api/dashboard", headers=headers)

    assert response.status_code == 200
    camera = response.json()["cameras"][0]
    assert camera["status"] == "unknown"
    assert camera["last_event"]["analysis"]["summary"] == "Último análisis válido."
    assert camera["latest_analysis_status"] == "failed"
    assert camera["latest_analysis_at"] is not None


def test_dashboard_requires_authentication(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)

    response = client.get("/api/dashboard")

    assert response.status_code == 401


def test_dashboard_keeps_captures_available_when_mongo_fails_without_leaking_details(
    tmp_path: Path,
) -> None:
    client, headers, capture_dir = _client(tmp_path, collection=BrokenCollection())
    camera_dir = capture_dir / "CAM1"
    camera_dir.mkdir(parents=True)
    (camera_dir / "latest.jpg").write_bytes(b"\xff\xd8live-frame\xff\xd9")

    response = client.get("/api/dashboard", headers=headers)

    assert response.status_code == 200
    camera = response.json()["cameras"][0]
    assert camera["last_event"] is None
    assert camera["status"] == "online"
    assert camera["latest_capture_url"].startswith("/cameras/CAM1/latest-frame?v=")
    assert camera["latest_capture_at"] is not None
    assert camera["latest_analysis_status"] == "unavailable"
    assert "Mongo is unavailable" not in response.text


def test_old_connected_event_does_not_keep_camera_online_forever(tmp_path: Path) -> None:
    old_connection = _connectivity_event(
        "CAM1",
        "camera.connected",
        datetime.now(UTC) - timedelta(hours=1),
    )
    client, headers, _ = _client(tmp_path, [old_connection])

    response = client.get("/api/dashboard", headers=headers)

    assert response.status_code == 200
    camera = response.json()["cameras"][0]
    assert camera["status"] == "waiting"
