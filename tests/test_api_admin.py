from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from iris import config_store
from iris.users_store import create_user

# Baseline explícito para las pruebas de /admin/cameras. SQLite gana para las
# claves persistidas y el entorno queda como fallback; guardar aquí cámara,
# proveedor y JWT mantiene cada caso totalmente determinista.
_CAMERA_BASELINE = {
    "CAM1_NAME": "Dormitorio",
    "CAM1_RTSP_URL": "rtsp://camera-one/live",
    "CAM1_PROMPT": "Vigila caídas visibles.",
    "DASHSCOPE_API_KEY": "test-secret-key",
    "DASHSCOPE_BASE_URL": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "AUTH_JWT_SECRET": "test-jwt-secret-at-least-32-bytes-long",
}


def _admin_client(api_app_factory: Callable) -> tuple[TestClient, str]:
    app, users_db, _ = api_app_factory()
    create_user(users_db, "admin", "s3cr3t", "admin")
    client = TestClient(app)
    login = client.post("/auth/login", json={"username": "admin", "password": "s3cr3t"})
    token = login.json()["access_token"]
    return client, token


def _normal_client(client: TestClient, users_db, username: str = "normie") -> str:
    create_user(users_db, username, "s3cr3t", "normal")
    login = client.post("/auth/login", json={"username": username, "password": "s3cr3t"})
    return login.json()["access_token"]


def _seeded_admin_client(api_app_factory: Callable, tmp_path: Path) -> tuple[TestClient, str, Path]:
    """Like ``_admin_client`` but with the full config baseline already in SQLite.

    ``api_app_factory`` places its config DB at ``tmp_path / "config.db"``; we
    write the baseline there *before* calling it so both the app's startup
    config and every subsequent ``load_config()`` reload done by the camera
    endpoints agree on the same source of truth.
    """

    config_db_path = tmp_path / "config.db"
    config_store.write_config_mapping(config_db_path, dict(_CAMERA_BASELINE))
    app, users_db, _ = api_app_factory()
    assert users_db == config_db_path
    create_user(users_db, "admin", "s3cr3t", "admin")
    client = TestClient(app)
    login = client.post("/auth/login", json={"username": "admin", "password": "s3cr3t"})
    token = login.json()["access_token"]
    return client, token, users_db


def test_admin_users_endpoints_require_admin_role(api_app_factory: Callable) -> None:
    app, users_db, _ = api_app_factory()
    create_user(users_db, "normie", "s3cr3t", "normal")
    client = TestClient(app)
    login = client.post("/auth/login", json={"username": "normie", "password": "s3cr3t"})
    token = login.json()["access_token"]

    response = client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


def test_admin_users_endpoints_reject_missing_token(api_app_factory: Callable) -> None:
    app, _, _ = api_app_factory()
    client = TestClient(app)

    response = client.get("/admin/users")

    assert response.status_code == 401


def test_list_users_returns_users_without_password_hash(api_app_factory: Callable) -> None:
    client, token = _admin_client(api_app_factory)

    response = client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    usernames = [user["username"] for user in body]
    assert "admin" in usernames
    for user in body:
        assert "password_hash" not in user
        assert set(user.keys()) == {"id", "username", "role", "is_active", "created_at"}


def test_create_user_returns_201_and_the_created_user(api_app_factory: Callable) -> None:
    client, token = _admin_client(api_app_factory)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/admin/users",
        json={"username": "carol", "password": "s3cr3t", "role": "normal"},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "carol"
    assert body["role"] == "normal"
    assert body["is_active"] is True
    assert "password_hash" not in body


def test_create_user_with_duplicate_username_returns_409(api_app_factory: Callable) -> None:
    client, token = _admin_client(api_app_factory)
    headers = {"Authorization": f"Bearer {token}"}
    client.post(
        "/admin/users",
        json={"username": "carol", "password": "s3cr3t", "role": "normal"},
        headers=headers,
    )

    response = client.post(
        "/admin/users",
        json={"username": "carol", "password": "other", "role": "normal"},
        headers=headers,
    )

    assert response.status_code == 409


def test_create_user_with_invalid_role_returns_400(api_app_factory: Callable) -> None:
    client, token = _admin_client(api_app_factory)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/admin/users",
        json={"username": "dave", "password": "s3cr3t", "role": "superuser"},
        headers=headers,
    )

    assert response.status_code == 400


def test_create_user_requires_admin_role(api_app_factory: Callable) -> None:
    app, users_db, _ = api_app_factory()
    client = TestClient(app)
    token = _normal_client(client, users_db)

    response = client.post(
        "/admin/users",
        json={"username": "eve", "password": "s3cr3t", "role": "normal"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_patch_user_updates_role_and_active(api_app_factory: Callable) -> None:
    client, token = _admin_client(api_app_factory)
    headers = {"Authorization": f"Bearer {token}"}
    client.post(
        "/admin/users",
        json={"username": "frank", "password": "s3cr3t", "role": "normal"},
        headers=headers,
    )

    response = client.patch(
        "/admin/users/frank",
        json={"role": "admin", "is_active": False},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "admin"
    assert body["is_active"] is False


def test_patch_user_on_unknown_username_returns_404(api_app_factory: Callable) -> None:
    client, token = _admin_client(api_app_factory)

    response = client.patch(
        "/admin/users/ghost",
        json={"role": "admin"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


def test_patch_user_requires_admin_role(api_app_factory: Callable) -> None:
    app, users_db, _ = api_app_factory()
    client = TestClient(app)
    token = _normal_client(client, users_db)

    response = client.patch(
        "/admin/users/normie",
        json={"role": "admin"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_get_settings_returns_editable_pipeline_shape(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, _ = _seeded_admin_client(api_app_factory, tmp_path)

    response = client.get("/admin/settings", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["revision"] >= 1
    assert body["frame_width"] == 640
    assert body["frame_height"] == 360
    assert body["jpeg_quality"] == 82
    assert body["max_api_calls_per_minute"] == 60
    assert body["save_image_min_severity"] == "high"
    assert body["change_threshold_percent"] == 0.0
    assert body["telegram_enabled"] is True
    assert body["telegram_configured"] is False
    assert body["alibaba_api_key_configured"] is True
    assert body["alibaba_base_url"] == "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    assert body["alibaba_model"] == "qwen3.6-flash"
    assert body["alibaba_timeout_seconds"] == 45.0
    assert body["alibaba_max_retries"] == 3
    assert body["alibaba_max_completion_tokens"] == 512
    assert set(body) == {
        "revision",
        "frame_width",
        "frame_height",
        "jpeg_quality",
        "max_api_calls_per_minute",
        "save_image_min_severity",
        "change_threshold_percent",
        "telegram_enabled",
        "telegram_configured",
        "alibaba_api_key_configured",
        "alibaba_base_url",
        "alibaba_model",
        "alibaba_timeout_seconds",
        "alibaba_max_retries",
        "alibaba_max_completion_tokens",
    }
    assert _CAMERA_BASELINE["DASHSCOPE_API_KEY"] not in response.text
    assert '"alibaba_api_key":' not in response.text
    assert "rtsp://" not in response.text.lower()


def test_patch_settings_updates_severity_and_get_reflects_it(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, _ = _seeded_admin_client(api_app_factory, tmp_path)
    headers = {"Authorization": f"Bearer {token}"}
    revision = client.get("/admin/settings", headers=headers).json()["revision"]

    patch_response = client.patch(
        "/admin/settings",
        json={"revision": revision, "save_image_min_severity": "critical"},
        headers=headers,
    )

    assert patch_response.status_code == 200
    assert patch_response.json()["save_image_min_severity"] == "critical"

    get_response = client.get("/admin/settings", headers=headers)
    assert get_response.json()["save_image_min_severity"] == "critical"


def test_patch_settings_toggles_telegram_enabled(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, config_db_path = _seeded_admin_client(api_app_factory, tmp_path)
    headers = {"Authorization": f"Bearer {token}"}
    revision = client.get("/admin/settings", headers=headers).json()["revision"]

    patch_response = client.patch(
        "/admin/settings",
        json={"revision": revision, "telegram_enabled": False},
        headers=headers,
    )

    assert patch_response.status_code == 200
    assert patch_response.json()["telegram_enabled"] is False
    stored = config_store.read_config_mapping(config_db_path)
    assert stored["ENABLE_TELEGRAM"].strip().lower() == "false"


def test_patch_settings_persists_pipeline_values_and_advances_revision(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, config_db_path = _seeded_admin_client(api_app_factory, tmp_path)
    headers = {"Authorization": f"Bearer {token}"}
    before = client.get("/admin/settings", headers=headers).json()

    response = client.patch(
        "/admin/settings",
        json={
            "revision": before["revision"],
            "frame_width": 800,
            "frame_height": 450,
            "jpeg_quality": 90,
        },
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["revision"] == before["revision"] + 1
    assert (body["frame_width"], body["frame_height"]) == (800, 450)
    assert body["jpeg_quality"] == 90
    stored = config_store.read_config_mapping(config_db_path)
    assert "DASHSCOPE_SYSTEM_PROMPT" not in stored
    assert stored["FRAME_WIDTH"] == "800"


def test_patch_settings_persists_alibaba_fields_but_never_returns_api_key(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, config_db_path = _seeded_admin_client(api_app_factory, tmp_path)
    headers = {"Authorization": f"Bearer {token}"}
    before = client.get("/admin/settings", headers=headers).json()
    replacement_key = "dashscope-replacement-secret"

    response = client.patch(
        "/admin/settings",
        json={
            "revision": before["revision"],
            "alibaba_api_key": replacement_key,
            "alibaba_base_url": ("https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
            "alibaba_model": "qwen-vl-max",
            "alibaba_timeout_seconds": 55,
            "alibaba_max_retries": 4,
            "alibaba_max_completion_tokens": 1_024,
        },
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["revision"] == before["revision"] + 1
    assert body["alibaba_api_key_configured"] is True
    assert body["alibaba_base_url"] == "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    assert body["alibaba_model"] == "qwen-vl-max"
    assert body["alibaba_timeout_seconds"] == 55.0
    assert body["alibaba_max_retries"] == 4
    assert body["alibaba_max_completion_tokens"] == 1_024
    assert replacement_key not in response.text
    assert '"alibaba_api_key":' not in response.text

    stored = config_store.read_config_mapping(config_db_path)
    assert stored["DASHSCOPE_API_KEY"] == replacement_key
    assert stored["DASHSCOPE_MODEL"] == "qwen-vl-max"


def test_patch_settings_blank_alibaba_key_keeps_secret_and_revision(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, config_db_path = _seeded_admin_client(api_app_factory, tmp_path)
    headers = {"Authorization": f"Bearer {token}"}
    before = client.get("/admin/settings", headers=headers).json()

    response = client.patch(
        "/admin/settings",
        json={"revision": before["revision"], "alibaba_api_key": "   "},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["revision"] == before["revision"]
    assert response.json()["alibaba_api_key_configured"] is True
    assert _CAMERA_BASELINE["DASHSCOPE_API_KEY"] not in response.text
    stored = config_store.read_config_mapping(config_db_path)
    assert stored["DASHSCOPE_API_KEY"] == _CAMERA_BASELINE["DASHSCOPE_API_KEY"]


def test_patch_settings_invalid_alibaba_base_url_rolls_back_key_without_leaking_it(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, config_db_path = _seeded_admin_client(api_app_factory, tmp_path)
    replacement_key = "must-never-appear-in-error"
    headers = {"Authorization": f"Bearer {token}"}
    revision = client.get("/admin/settings", headers=headers).json()["revision"]

    response = client.patch(
        "/admin/settings",
        json={
            "revision": revision,
            "alibaba_api_key": replacement_key,
            "alibaba_base_url": "http://insecure.example/compatible-mode/v1",
        },
        headers=headers,
    )

    assert response.status_code == 422
    assert replacement_key not in response.text
    assert '"input"' not in response.text
    stored = config_store.read_config_mapping(config_db_path)
    assert stored["DASHSCOPE_API_KEY"] == _CAMERA_BASELINE["DASHSCOPE_API_KEY"]


def test_patch_settings_rejects_non_alibaba_https_endpoint(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, config_db_path = _seeded_admin_client(api_app_factory, tmp_path)
    headers = {"Authorization": f"Bearer {token}"}
    revision = client.get("/admin/settings", headers=headers).json()["revision"]

    response = client.patch(
        "/admin/settings",
        json={
            "revision": revision,
            "alibaba_base_url": "https://attacker.example/compatible-mode/v1",
        },
        headers=headers,
    )

    assert response.status_code == 422
    assert "attacker.example" not in response.text
    assert (
        config_store.read_config_mapping(config_db_path)["DASHSCOPE_BASE_URL"]
        == (_CAMERA_BASELINE["DASHSCOPE_BASE_URL"])
    )


def test_patch_settings_invalid_api_key_type_is_not_echoed_in_422(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, _ = _seeded_admin_client(api_app_factory, tmp_path)
    headers = {"Authorization": f"Bearer {token}"}
    revision = client.get("/admin/settings", headers=headers).json()["revision"]
    marker = "secret-that-must-not-be-echoed"

    response = client.patch(
        "/admin/settings",
        json={
            "revision": revision,
            "alibaba_api_key": {"nested": marker},
        },
        headers=headers,
    )

    assert response.status_code == 422
    assert marker not in response.text
    assert '"input"' not in response.text


def test_patch_settings_rejects_removed_global_polling_field(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, config_db_path = _seeded_admin_client(api_app_factory, tmp_path)
    headers = {"Authorization": f"Bearer {token}"}
    revision = client.get("/admin/settings", headers=headers).json()["revision"]

    response = client.patch(
        "/admin/settings",
        json={"revision": revision, "poll_interval_seconds": 30},
        headers=headers,
    )

    assert response.status_code == 422
    assert "CAM1_POLL_INTERVAL_SECONDS" not in config_store.read_config_mapping(config_db_path)


def test_patch_settings_rejects_stale_revision_without_lost_update(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, _ = _seeded_admin_client(api_app_factory, tmp_path)
    headers = {"Authorization": f"Bearer {token}"}
    revision = client.get("/admin/settings", headers=headers).json()["revision"]
    first = client.patch(
        "/admin/settings",
        json={"revision": revision, "jpeg_quality": 83},
        headers=headers,
    )
    stale = client.patch(
        "/admin/settings",
        json={"revision": revision, "jpeg_quality": 84},
        headers=headers,
    )

    assert first.status_code == 200
    assert stale.status_code == 409
    assert client.get("/admin/settings", headers=headers).json()["jpeg_quality"] == 83


def test_patch_settings_rejects_invalid_severity(api_app_factory: Callable, tmp_path: Path) -> None:
    client, token, _ = _seeded_admin_client(api_app_factory, tmp_path)
    headers = {"Authorization": f"Bearer {token}"}
    revision = client.get("/admin/settings", headers=headers).json()["revision"]

    response = client.patch(
        "/admin/settings",
        json={"revision": revision, "save_image_min_severity": "catastrophic"},
        headers=headers,
    )

    assert response.status_code == 400


def test_patch_settings_requires_admin_role(api_app_factory: Callable) -> None:
    app, users_db, _ = api_app_factory()
    client = TestClient(app)
    token = _normal_client(client, users_db)

    response = client.patch(
        "/admin/settings",
        json={"revision": 0, "save_image_min_severity": "critical"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_get_settings_requires_admin_role(api_app_factory: Callable, tmp_path: Path) -> None:
    config_db_path = tmp_path / "config.db"
    config_store.write_config_mapping(config_db_path, dict(_CAMERA_BASELINE))
    app, users_db, _ = api_app_factory()
    client = TestClient(app)
    token = _normal_client(client, users_db)

    response = client.get("/admin/settings", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


def test_patch_settings_with_no_fields_returns_400(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, _ = _seeded_admin_client(api_app_factory, tmp_path)
    headers = {"Authorization": f"Bearer {token}"}
    revision = client.get("/admin/settings", headers=headers).json()["revision"]

    response = client.patch("/admin/settings", json={"revision": revision}, headers=headers)

    assert response.status_code == 400


def test_patch_settings_requires_revision(api_app_factory: Callable, tmp_path: Path) -> None:
    client, token, _ = _seeded_admin_client(api_app_factory, tmp_path)

    response = client.patch(
        "/admin/settings",
        json={"jpeg_quality": 90},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422


# --- /admin/cameras -----------------------------------------------------


def test_get_cameras_returns_full_rtsp_url_prompt_and_polling(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, _ = _seeded_admin_client(api_app_factory, tmp_path)

    response = client.get("/admin/cameras", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == [
        {
            "index": 1,
            "id": "CAM1",
            "name": "Dormitorio",
            "rtsp_url": "rtsp://camera-one/live",
            "prompt": "Vigila caídas visibles.",
            "poll_interval_seconds": 30.0,
            "notification_threshold": "high",
        }
    ]
    assert "rtsp://camera-one/live" in response.text


def test_post_camera_creates_second_camera_with_next_index(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, _ = _seeded_admin_client(api_app_factory, tmp_path)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/admin/cameras",
        json={
            "name": "Living",
            "rtsp_url": "rtsp://camera-two/live",
            "prompt": "Vigila la sala de estar.",
            "poll_interval_seconds": 45,
        },
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["index"] == 2
    assert body["id"] == "CAM2"
    assert body["name"] == "Living"
    assert body["rtsp_url"] == "rtsp://camera-two/live"
    assert body["prompt"] == "Vigila la sala de estar."
    assert body["poll_interval_seconds"] == 45.0
    assert body["notification_threshold"] == "high"
    assert set(body) == {
        "index",
        "id",
        "name",
        "rtsp_url",
        "prompt",
        "poll_interval_seconds",
        "notification_threshold",
    }

    get_response = client.get("/admin/cameras", headers=headers)
    indices = [camera["index"] for camera in get_response.json()]
    assert indices == [1, 2]


def test_post_camera_rejects_polling_below_ten_seconds(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, config_db_path = _seeded_admin_client(api_app_factory, tmp_path)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/admin/cameras",
        json={
            "name": "Living",
            "rtsp_url": "rtsp://camera-two/live",
            "prompt": "Vigila la sala de estar.",
            "poll_interval_seconds": 9.9,
        },
        headers=headers,
    )

    assert response.status_code == 422
    stored = config_store.read_config_mapping(config_db_path)
    assert not any(key.startswith("CAM2_") for key in stored)


def test_post_camera_with_invalid_rtsp_url_returns_400_without_partial_state(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, config_db_path = _seeded_admin_client(api_app_factory, tmp_path)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/admin/cameras",
        json={
            "name": "Living",
            "rtsp_url": "rtsp://camera two/live",  # space: rejected by iris.config._rtsp_url
            "prompt": "Vigila la sala de estar.",
        },
        headers=headers,
    )

    assert response.status_code == 400

    get_response = client.get("/admin/cameras", headers=headers)
    assert [camera["index"] for camera in get_response.json()] == [1]

    stored = config_store.read_config_mapping(config_db_path)
    assert not any(key.startswith("CAM2_") for key in stored)


def test_post_camera_requires_admin_role(api_app_factory: Callable, tmp_path: Path) -> None:
    config_db_path = tmp_path / "config.db"
    config_store.write_config_mapping(config_db_path, dict(_CAMERA_BASELINE))
    app, users_db, _ = api_app_factory()
    client = TestClient(app)
    token = _normal_client(client, users_db)

    response = client.post(
        "/admin/cameras",
        json={"name": "Living", "rtsp_url": "rtsp://camera-two/live", "prompt": "Vigila."},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_patch_camera_updates_only_prompt(api_app_factory: Callable, tmp_path: Path) -> None:
    client, token, config_db_path = _seeded_admin_client(api_app_factory, tmp_path)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.patch(
        "/admin/cameras/1",
        json={"prompt": "Nuevo prompt de vigilancia."},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["prompt"] == "Nuevo prompt de vigilancia."
    assert body["name"] == "Dormitorio"

    stored = config_store.read_config_mapping(config_db_path)
    assert stored["CAM1_PROMPT"] == "Nuevo prompt de vigilancia."
    assert stored["CAM1_NAME"] == "Dormitorio"
    assert stored["CAM1_RTSP_URL"] == "rtsp://camera-one/live"


def test_post_camera_accepts_custom_notification_threshold(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, config_db_path = _seeded_admin_client(api_app_factory, tmp_path)

    response = client.post(
        "/admin/cameras",
        json={
            "name": "Living",
            "rtsp_url": "rtsp://camera-two/live",
            "prompt": "Vigila la sala de estar.",
            "notification_threshold": "critical",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    assert response.json()["notification_threshold"] == "critical"
    stored = config_store.read_config_mapping(config_db_path)
    assert stored["CAM2_NOTIFICATION_THRESHOLD"] == "critical"


def test_patch_camera_updates_notification_threshold(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, config_db_path = _seeded_admin_client(api_app_factory, tmp_path)

    response = client.patch(
        "/admin/cameras/1",
        json={"notification_threshold": "medium"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["notification_threshold"] == "medium"
    stored = config_store.read_config_mapping(config_db_path)
    assert stored["CAM1_NOTIFICATION_THRESHOLD"] == "medium"


def test_patch_camera_rejects_invalid_notification_threshold(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, _ = _seeded_admin_client(api_app_factory, tmp_path)

    response = client.patch(
        "/admin/cameras/1",
        json={"notification_threshold": "urgentisimo"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400


def test_patch_camera_blank_rtsp_keeps_stored_secret(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, config_db_path = _seeded_admin_client(api_app_factory, tmp_path)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.patch(
        "/admin/cameras/1",
        json={"rtsp_url": "", "name": "Dormitorio norte"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["rtsp_url"] == "rtsp://camera-one/live"
    stored = config_store.read_config_mapping(config_db_path)
    assert stored["CAM1_RTSP_URL"] == "rtsp://camera-one/live"


def test_patch_camera_updates_per_camera_poll_interval(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, config_db_path = _seeded_admin_client(api_app_factory, tmp_path)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.patch(
        "/admin/cameras/1",
        json={"poll_interval_seconds": 45.0},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["poll_interval_seconds"] == 45.0
    stored = config_store.read_config_mapping(config_db_path)
    assert stored["CAM1_POLL_INTERVAL_SECONDS"] == "45.0"


def test_patch_camera_rejects_poll_interval_below_ten_seconds(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, config_db_path = _seeded_admin_client(api_app_factory, tmp_path)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.patch(
        "/admin/cameras/1",
        json={"poll_interval_seconds": 9.9},
        headers=headers,
    )

    assert response.status_code == 422
    assert "CAM1_POLL_INTERVAL_SECONDS" not in config_store.read_config_mapping(config_db_path)


def test_initial_api_start_persists_dashscope_api_key(
    api_app_factory: Callable,
) -> None:
    _, config_db_path, _ = api_app_factory()

    stored = config_store.read_config_mapping(config_db_path)

    assert stored["DASHSCOPE_API_KEY"] == "test-secret-key"


def test_patch_camera_rejects_per_camera_threshold_override(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, config_db_path = _seeded_admin_client(api_app_factory, tmp_path)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.patch(
        "/admin/cameras/1",
        json={"change_threshold_percent": 250},
        headers=headers,
    )

    assert response.status_code == 422

    stored = config_store.read_config_mapping(config_db_path)
    assert "CAM1_CHANGE_THRESHOLD_PERCENT" not in stored


def test_patch_camera_on_unknown_index_returns_404(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, _ = _seeded_admin_client(api_app_factory, tmp_path)

    response = client.patch(
        "/admin/cameras/99",
        json={"prompt": "Nuevo prompt."},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


def test_patch_camera_requires_admin_role(api_app_factory: Callable, tmp_path: Path) -> None:
    config_db_path = tmp_path / "config.db"
    config_store.write_config_mapping(config_db_path, dict(_CAMERA_BASELINE))
    app, users_db, _ = api_app_factory()
    client = TestClient(app)
    token = _normal_client(client, users_db)

    response = client.patch(
        "/admin/cameras/1",
        json={"prompt": "Nuevo prompt."},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_delete_camera_removes_it(api_app_factory: Callable, tmp_path: Path) -> None:
    client, token, _ = _seeded_admin_client(api_app_factory, tmp_path)
    headers = {"Authorization": f"Bearer {token}"}
    client.post(
        "/admin/cameras",
        json={"name": "Living", "rtsp_url": "rtsp://camera-two/live", "prompt": "Vigila."},
        headers=headers,
    )

    response = client.delete("/admin/cameras/2", headers=headers)

    assert response.status_code == 200
    assert response.json()["index"] == 2

    get_response = client.get("/admin/cameras", headers=headers)
    assert [camera["index"] for camera in get_response.json()] == [1]


def test_delete_last_remaining_camera_is_rejected(
    api_app_factory: Callable, tmp_path: Path
) -> None:
    client, token, _ = _seeded_admin_client(api_app_factory, tmp_path)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.delete("/admin/cameras/1", headers=headers)

    assert response.status_code == 400

    get_response = client.get("/admin/cameras", headers=headers)
    assert [camera["index"] for camera in get_response.json()] == [1]


def test_delete_camera_requires_admin_role(api_app_factory: Callable, tmp_path: Path) -> None:
    config_db_path = tmp_path / "config.db"
    config_store.write_config_mapping(config_db_path, dict(_CAMERA_BASELINE))
    app, users_db, _ = api_app_factory()
    client = TestClient(app)
    token = _normal_client(client, users_db)

    response = client.delete("/admin/cameras/1", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


def test_get_cameras_requires_admin_role(api_app_factory: Callable, tmp_path: Path) -> None:
    config_db_path = tmp_path / "config.db"
    config_store.write_config_mapping(config_db_path, dict(_CAMERA_BASELINE))
    app, users_db, _ = api_app_factory()
    client = TestClient(app)
    token = _normal_client(client, users_db)

    response = client.get("/admin/cameras", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
