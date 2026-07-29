from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from iris import config_store
from iris.sinks import CaptureStore
from iris.users_store import create_user

AUTH_USERNAME = "viewer"


# Baseline explícito para /cameras/{id}/latest-frame. SQLite gana para las
# claves persistidas y el entorno queda como fallback; sembramos también
# CAPTURE_DIR para que el router y el fixture resuelvan exactamente la misma
# ubicación.
def _seeded_client(api_app_factory: Callable, tmp_path: Path) -> tuple[TestClient, str, Path]:
    config_db_path = tmp_path / "config.db"
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir(exist_ok=True)
    config_store.write_config_mapping(
        config_db_path,
        {
            "CAM1_NAME": "Dormitorio",
            "CAM1_RTSP_URL": "rtsp://camera-one/live",
            "CAM1_PROMPT": "Vigila caídas visibles.",
            "DASHSCOPE_API_KEY": "test-secret-key",
            "DASHSCOPE_BASE_URL": ("https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
            "AUTH_JWT_SECRET": "test-jwt-secret-at-least-32-bytes-long",
            "CAPTURE_DIR": str(capture_dir),
        },
    )
    app, users_db, factory_capture_dir = api_app_factory()
    assert users_db == config_db_path
    assert factory_capture_dir == capture_dir

    create_user(users_db, AUTH_USERNAME, "s3cr3t", "normal")
    client = TestClient(app)
    login = client.post("/auth/login", json={"username": AUTH_USERNAME, "password": "s3cr3t"})
    token = login.json()["access_token"]
    return client, token, capture_dir


def test_latest_frame_missing_returns_404_for_a_configured_camera(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, _ = _seeded_client(api_app_factory, tmp_path)

    response = client.get(
        "/cameras/CAM1/latest-frame", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 404


def test_latest_frame_unknown_camera_returns_404(api_app_factory: Callable, tmp_path: Path) -> None:
    client, token, _ = _seeded_client(api_app_factory, tmp_path)

    response = client.get(
        "/cameras/CAM99/latest-frame", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 404


def test_latest_frame_happy_path_returns_jpeg_with_no_store_cache_header(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, capture_dir = _seeded_client(api_app_factory, tmp_path)
    store = CaptureStore(capture_dir, enabled=False)
    store.save_latest(b"\xff\xd8\xff\xd9fake-latest-jpeg", camera_id="CAM1")

    response = client.get(
        "/cameras/CAM1/latest-frame", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "no-store"
    assert response.content == b"\xff\xd8\xff\xd9fake-latest-jpeg"


def test_latest_frame_works_with_no_mongo_configured(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    # Unlike /detections/*, this endpoint never touches Mongo at all: it only
    # reads a file from config.capture_dir. No MONGO_URI is set anywhere in
    # this test (the seeded baseline above omits it entirely), so a 200 here
    # alone proves independence from Mongo.
    client, token, capture_dir = _seeded_client(api_app_factory, tmp_path)
    store = CaptureStore(capture_dir, enabled=False)
    store.save_latest(b"\xff\xd8\xff\xd9fake-latest-jpeg", camera_id="CAM1")

    response = client.get(
        "/cameras/CAM1/latest-frame", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200


def test_latest_frame_without_token_is_rejected(api_app_factory: Callable, tmp_path: Path) -> None:
    client, _, _ = _seeded_client(api_app_factory, tmp_path)

    response = client.get("/cameras/CAM1/latest-frame")

    assert response.status_code == 401


def test_versioned_event_frame_returns_exact_immutable_preview(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, capture_dir = _seeded_client(api_app_factory, tmp_path)
    store = CaptureStore(capture_dir, enabled=False)
    event_id = "832e8c5a7f6c4bf9b1066a387928fa28"
    store.save_preview(
        b"\xff\xd8event-specific\xff\xd9",
        camera_id="CAM1",
        event_id=event_id,
    )

    response = client.get(
        f"/cameras/CAM1/events/{event_id}/frame",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.content == b"\xff\xd8event-specific\xff\xd9"
    assert response.headers["etag"] == f'"{event_id}"'
    assert response.headers["cache-control"] == "private, no-store"


def test_versioned_event_frame_rejects_invalid_event_id(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, _ = _seeded_client(api_app_factory, tmp_path)

    response = client.get(
        "/cameras/CAM1/events/not!safe/frame",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


# Path-traversal note: unlike /detections/{id}/image (which reads an
# attacker-influenced snapshot_path out of a Mongo document), this endpoint
# only builds a filesystem path from `camera_id` *after* confirming it
# matches exactly one of the currently configured camera identifiers (e.g.
# "CAM1"). A traversal payload such as "../../etc/passwd" cannot reach that
# point here: FastAPI/Starlette's default {camera_id} path converter rejects
# "/" inside the segment entirely (it 404s at routing time, before the
# handler ever runs), and even a slash-free payload (e.g. "..") would still
# fail the configured-camera-identifier equality check with a 404 -- which
# is exactly what test_latest_frame_unknown_camera_returns_404 above already
# exercises. So there is no additional, meaningful path-traversal test to add
# beyond that: the containment check inside the handler (mirroring
# routes_detections.py byte-for-byte) is defense in depth for a path this
# route's shape already closes off before the handler body runs.
