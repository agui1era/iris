from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


@pytest.fixture
def base_env() -> dict[str, str]:
    return {
        "CAM1_RTSP_URL": "rtsp://camera-one/live",
        "CAM1_PROMPT": "Vigila caídas visibles.",
        "DASHSCOPE_API_KEY": "test-secret-key",
        "DASHSCOPE_BASE_URL": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    }


@pytest.fixture
def api_app_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., tuple[object, Path, Path]]:
    """Builds an ``iris.api`` FastAPI app wired to isolated tmp_path stores.

    Returns a factory ``(**env_overrides) -> (app, users_db_path, capture_dir)``
    so tests can create the app with sane defaults (a valid camera, DashScope
    credentials, AUTH_JWT_SECRET, an isolated CAPTURE_DIR) and override just
    the bits they care about (e.g. AUTH_JWT_SECRET="" to test the missing-secret
    failure, or MONGO_URI when relevant).
    """

    def _factory(**env_overrides: str) -> tuple[object, Path, Path]:
        from iris.api.app import create_app

        users_db_path = tmp_path / "config.db"
        capture_dir = tmp_path / "captures"
        capture_dir.mkdir(exist_ok=True)
        env: dict[str, str] = {
            "CAM1_RTSP_URL": "rtsp://camera-one/live",
            "CAM1_PROMPT": "Vigila caídas visibles.",
            "DASHSCOPE_API_KEY": "test-secret-key",
            "DASHSCOPE_BASE_URL": ("https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
            "AUTH_JWT_SECRET": "test-jwt-secret-at-least-32-bytes-long",
            "CAPTURE_DIR": str(capture_dir),
        }
        env.update(env_overrides)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        app = create_app(config_db_path=users_db_path, dotenv_path=tmp_path / "unused.env")
        return app, users_db_path, capture_dir

    return _factory
