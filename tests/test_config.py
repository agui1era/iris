from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from iris import config_store
from iris.config import ConfigurationError, load_config, sanitized_config


def test_loads_all_cameras_and_inherits_global_polling_default(
    base_env: dict[str, str],
) -> None:
    env = {
        **base_env,
        "CAM3_RTSP_URL": "rtsp://camera-three/live",
        "CAM3_PROMPT": "Vigila la salida.",
        "CAM2_RTSP_URL": "rtsp://camera-two/live",
        "CAM2_PROMPT": "Vigila inmovilidad.",
        "POLL_INTERVAL_SECONDS": "45",
    }

    config = load_config(env)

    assert [camera.index for camera in config.cameras] == [1, 2, 3]
    assert [camera.identifier for camera in config.cameras] == ["CAM1", "CAM2", "CAM3"]
    assert [camera.rtsp_url for camera in config.cameras] == [
        "rtsp://camera-one/live",
        "rtsp://camera-two/live",
        "rtsp://camera-three/live",
    ]
    assert config.poll_interval_seconds == pytest.approx(45)
    assert [camera.poll_interval_seconds for camera in config.cameras] == [45, 45, 45]


def test_resolution_is_global_and_polling_can_vary_by_camera(
    base_env: dict[str, str],
    caplog,
) -> None:
    env = {
        **base_env,
        "FRAME_WIDTH": "960",
        "FRAME_HEIGHT": "540",
        "CHANGE_THRESHOLD_PERCENT": "7.5",
        "CAM1_FRAME_WIDTH": "",
        "CAM2_RTSP_URL": "rtsp://camera-two/live",
        "CAM2_NAME": "Dormitorio principal",
        "CAM2_PROMPT": "Prompt del dormitorio",
        "CAM2_FRAME_WIDTH": "1280",
        "CAM2_FRAME_HEIGHT": "720",
        "CAM2_CHANGE_THRESHOLD_PERCENT": "13.25",
        "CAM2_POLL_INTERVAL_SECONDS": "90",
    }

    config = load_config(env)

    first, second = config.cameras
    assert (config.frame_width, config.frame_height) == (960, 540)
    assert config.poll_interval_seconds == 30
    assert second.name == "Dormitorio principal"
    assert second.prompt == "Prompt del dormitorio"
    assert first.poll_interval_seconds == 30
    assert second.poll_interval_seconds == 90
    assert not hasattr(first, "width")
    assert "opciones legacy" in caplog.text


def test_poll_interval_defaults_to_thirty_seconds_when_unset(
    base_env: dict[str, str],
) -> None:
    config = load_config(base_env)

    assert config.poll_interval_seconds == pytest.approx(30.0)


def test_rejects_global_poll_interval_below_thirty_seconds(
    base_env: dict[str, str],
) -> None:
    with pytest.raises(ConfigurationError, match="mayor o igual a 30"):
        load_config({**base_env, "POLL_INTERVAL_SECONDS": "29.9"})


def test_rejects_camera_poll_interval_below_thirty_seconds(
    base_env: dict[str, str],
) -> None:
    with pytest.raises(ConfigurationError, match="CAM1_POLL_INTERVAL_SECONDS.*30"):
        load_config({**base_env, "CAM1_POLL_INTERVAL_SECONDS": "29.9"})


def test_supports_legacy_urls_and_noncontiguous_camera_indices(
    base_env: dict[str, str],
) -> None:
    env = {
        key: value for key, value in base_env.items() if key not in {"CAM1_RTSP_URL", "CAM1_PROMPT"}
    }
    env.update(
        {
            "VITE_RTSP_URL_CAM1": "rtsp://legacy-camera-one/live",
            "CAM1_PROMPT": "Prompt cámara uno.",
            "VITE_RTSP_URL_CAM3": "rtsp://legacy-camera-three/live",
            "CAM3_RTSP_URL": "rtsp://preferred-camera-three/live",
            "CAM3_PROMPT": "Prompt cámara tres.",
            "CAM4_RTSP_URL": "rtsp://camera-four/live",
            "CAM4_PROMPT": "Prompt cámara cuatro.",
            "VITE_RTSP_URL_CAM6": "rtsp://legacy-camera-six/live",
            "CAM6_PROMPT": "Prompt cámara seis.",
        }
    )

    config = load_config(env)

    assert [camera.index for camera in config.cameras] == [1, 3, 4, 6]
    assert [camera.rtsp_url for camera in config.cameras] == [
        "rtsp://legacy-camera-one/live",
        "rtsp://preferred-camera-three/live",
        "rtsp://camera-four/live",
        "rtsp://legacy-camera-six/live",
    ]


def test_rejects_camera_without_own_or_default_prompt(
    base_env: dict[str, str],
) -> None:
    env = {key: value for key, value in base_env.items() if key != "CAM1_PROMPT"}

    with pytest.raises(ConfigurationError, match="CAM1_PROMPT"):
        load_config(env)


def test_sanitized_config_redacts_camera_urls_prompts_and_api_key(
    base_env: dict[str, str],
) -> None:
    config = load_config(base_env)

    safe = sanitized_config(config)
    serialized = repr(safe)

    assert safe["cameras"][0]["rtsp_url"] == "<redacted>"
    assert safe["cameras"][0]["prompt"] == "<configured>"
    assert config.alibaba.api_key not in serialized
    assert config.cameras[0].rtsp_url not in serialized
    assert config.cameras[0].prompt not in serialized


def test_loads_dashscope_key_and_endpoint_from_workspace_csv(
    base_env: dict[str, str],
    tmp_path: Path,
) -> None:
    credentials = tmp_path / "workspace.csv"
    credentials.write_text(
        "\ufeffid,\n"
        "apiKey,secret-from-csv\n"
        "openAiCompatible,https://dashscope-intl.aliyuncs.com/compatible-mode/v1\n"
        "workspaceId,ws-test\n",
        encoding="utf-8",
    )
    env = {
        key: value
        for key, value in base_env.items()
        if key not in {"DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL"}
    }
    env["DASHSCOPE_CREDENTIALS_CSV"] = str(credentials)

    config = load_config(env)

    assert config.alibaba.api_key == "secret-from-csv"
    assert config.alibaba.base_url == ("https://dashscope-intl.aliyuncs.com/compatible-mode/v1")


def test_explicit_dashscope_values_take_priority_over_workspace_csv(
    base_env: dict[str, str],
) -> None:
    env = {
        **base_env,
        "DASHSCOPE_CREDENTIALS_CSV": "/path/that/does/not/exist.csv",
    }

    config = load_config(env)

    assert config.alibaba.api_key == base_env["DASHSCOPE_API_KEY"]
    assert config.alibaba.base_url == base_env["DASHSCOPE_BASE_URL"]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("POLL_INTERVAL_SECONDS", "nan"),
        ("FRAME_STALE_AFTER_SECONDS", "inf"),
        ("DASHSCOPE_TIMEOUT_SECONDS", "+inf"),
    ],
)
def test_rejects_non_finite_numeric_configuration(
    base_env: dict[str, str],
    name: str,
    value: str,
) -> None:
    with pytest.raises(ConfigurationError, match="finito"):
        load_config({**base_env, name: value})


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("CAM1_RTSP_URL", "rtsp://camera.local:notaport/live", "RTSP inválida"),
        ("CAM1_RTSP_URL", "rtsp://bad host/live", "espacios"),
        (
            "DASHSCOPE_BASE_URL",
            "https:///compatible-mode/v1",
            "https:// válida",
        ),
        (
            "DASHSCOPE_BASE_URL",
            "https://user:pass@example.test/compatible-mode/v1",
            "credenciales",
        ),
        (
            "DASHSCOPE_BASE_URL",
            "https://example.test/v1",
            "compatible-mode/v1",
        ),
        (
            "DASHSCOPE_BASE_URL",
            "https://attacker.example/compatible-mode/v1",
            "endpoint oficial",
        ),
    ],
)
def test_rejects_malformed_or_unsafe_endpoints(
    base_env: dict[str, str],
    name: str,
    value: str,
    message: str,
) -> None:
    with pytest.raises(ConfigurationError, match=message):
        load_config({**base_env, name: value})


def test_rejects_alibaba_timeout_above_five_minutes(
    base_env: dict[str, str],
) -> None:
    with pytest.raises(ConfigurationError, match="menor o igual a 300"):
        load_config({**base_env, "DASHSCOPE_TIMEOUT_SECONDS": "301"})


def test_rejects_global_resolution_above_pixel_budget(
    base_env: dict[str, str],
) -> None:
    env = {
        **base_env,
        "FRAME_WIDTH": "4096",
        "FRAME_HEIGHT": "4096",
    }

    with pytest.raises(ConfigurationError, match="MAX_FRAME_PIXELS"):
        load_config(env)


def test_users_only_database_does_not_hide_environment_configuration(
    base_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "config.db"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()
    for key, value in base_env.items():
        monkeypatch.setenv(key, value)

    config = load_config(
        dotenv_path=tmp_path / "missing.env",
        config_db_path=db_path,
    )

    assert [camera.identifier for camera in config.cameras] == ["CAM1"]
    assert config.alibaba.api_key == base_env["DASHSCOPE_API_KEY"]
    assert config.config_revision == 0


def test_initialized_database_overrides_dynamic_environment_values(
    base_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for key, value in base_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "30")
    db_path = tmp_path / "config.db"
    config_store.initialize_config_mapping(
        db_path,
        {
            "CAM1_RTSP_URL": base_env["CAM1_RTSP_URL"],
            "CAM1_PROMPT": base_env["CAM1_PROMPT"],
            "POLL_INTERVAL_SECONDS": "45",
        },
    )

    config = load_config(
        dotenv_path=tmp_path / "missing.env",
        config_db_path=db_path,
    )

    assert config.poll_interval_seconds == 45
    assert config.config_revision == 1


def test_sqlite_mapping_and_revision_are_loaded_from_one_snapshot(
    base_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for key, value in base_env.items():
        monkeypatch.setenv(key, value)
    db_path = tmp_path / "config.db"
    config_store.initialize_config_mapping(
        db_path,
        {
            "CAM1_RTSP_URL": base_env["CAM1_RTSP_URL"],
            "CAM1_PROMPT": base_env["CAM1_PROMPT"],
            "POLL_INTERVAL_SECONDS": "45",
        },
    )
    original_snapshot = config_store.read_config_snapshot
    calls = 0

    def tracked_snapshot(path: Path) -> tuple[dict[str, str], int]:
        nonlocal calls
        calls += 1
        return original_snapshot(path)

    monkeypatch.setattr(config_store, "read_config_snapshot", tracked_snapshot)
    monkeypatch.setattr(
        config_store,
        "read_config_mapping",
        lambda _path: pytest.fail("load_config must not split mapping and revision reads"),
    )

    config = load_config(config_db_path=db_path, dotenv_path=tmp_path / "missing.env")

    assert calls == 1
    assert config.poll_interval_seconds == 45
    assert config.config_revision == 1


def test_accepts_existing_sentinex_mongo_variable_names(
    base_env: dict[str, str],
) -> None:
    config = load_config(
        {
            **base_env,
            "SENTINEX_MONGO_URI": "mongodb://localhost:27017",
            "SENTINEX_MONGO_DB": "omnistatus",
            "SENTINEX_MONGO_DETECTION_COLLECTION": "sentinex_face_rtsp_detections",
        }
    )

    assert config.mongo_uri == "mongodb://localhost:27017"
    assert config.mongo_database == "omnistatus"
    assert config.mongo_detection_collection == "sentinex_face_rtsp_detections"
