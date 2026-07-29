from __future__ import annotations

from pathlib import Path

from iris import config_store
from iris.__main__ import main


def _write_valid_env(path: Path, *, api_key: str = "first-secret") -> None:
    path.write_text(
        "\n".join(
            [
                "CAM1_RTSP_URL=rtsp://camera-one/live",
                "CAM1_PROMPT=Vigila riesgos visibles.",
                f"DASHSCOPE_API_KEY={api_key}",
                ("DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
                "POLL_INTERVAL_SECONDS=30",
                "UNRELATED_SECRET=must-not-be-imported",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_migrate_env_is_validated_filtered_and_one_shot(
    tmp_path: Path,
    capsys,
) -> None:
    dotenv_path = tmp_path / ".env"
    db_path = tmp_path / "config.db"
    _write_valid_env(dotenv_path)

    result = main(
        [
            "--migrate-env-to-sqlite",
            "--dotenv-path",
            str(dotenv_path),
            "--config-db",
            str(db_path),
        ]
    )

    assert result == 0
    stored = config_store.read_config_mapping(db_path)
    assert stored["DASHSCOPE_API_KEY"] == "first-secret"
    assert "UNRELATED_SECRET" not in stored
    assert "validadas" in capsys.readouterr().out

    _write_valid_env(dotenv_path, api_key="replacement-that-must-not-win")
    second = main(
        [
            "--migrate-env-to-sqlite",
            "--dotenv-path",
            str(dotenv_path),
            "--config-db",
            str(db_path),
        ]
    )

    assert second == 2
    assert config_store.read_config_mapping(db_path)["DASHSCOPE_API_KEY"] == "first-secret"
    assert "one-shot" in capsys.readouterr().err


def test_migrate_env_rejects_invalid_candidate_before_writing(
    tmp_path: Path,
) -> None:
    dotenv_path = tmp_path / ".env"
    db_path = tmp_path / "config.db"
    _write_valid_env(dotenv_path)
    with dotenv_path.open("a", encoding="utf-8") as stream:
        stream.write("POLL_INTERVAL_SECONDS=10\n")

    result = main(
        [
            "--migrate-env-to-sqlite",
            "--dotenv-path",
            str(dotenv_path),
            "--config-db",
            str(db_path),
        ]
    )

    assert result == 2
    assert not config_store.is_config_initialized(db_path)
