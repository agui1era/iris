from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import iris.config_store as config_store_module
from iris.config_store import (
    ConfigRevisionConflict,
    bump_config_revision,
    import_dotenv_into_db,
    initialize_config_mapping,
    is_config_initialized,
    mutate_config_mapping,
    read_config_mapping,
    read_config_revision,
    read_config_snapshot,
    write_config_mapping,
)


def test_bump_revision_requests_reload_without_changing_values(tmp_path: Path) -> None:
    path = tmp_path / "config.db"
    initialize_config_mapping(path, {"CAM1_NAME": "Pasillo"})
    before_mapping, before_revision = read_config_snapshot(path)

    revision = bump_config_revision(path)

    assert revision == before_revision + 1
    assert read_config_snapshot(path) == (before_mapping, revision)


def test_write_then_read_round_trips_values(tmp_path: Path) -> None:
    path = tmp_path / "private" / "config.db"

    write_config_mapping(path, {"RTSP_PASSWORD": "s3cr3t", "API_KEY": "abc123"})

    assert read_config_mapping(path) == {"RTSP_PASSWORD": "s3cr3t", "API_KEY": "abc123"}
    assert is_config_initialized(path)
    assert read_config_revision(path) == 1


def test_write_config_mapping_upserts_without_duplicating_rows(tmp_path: Path) -> None:
    path = tmp_path / "config.db"

    write_config_mapping(path, {"API_KEY": "old-value"})
    write_config_mapping(path, {"API_KEY": "new-value"})

    assert read_config_mapping(path) == {"API_KEY": "new-value"}


def test_config_db_and_parent_directory_have_private_permissions(tmp_path: Path) -> None:
    path = tmp_path / "private" / "config.db"

    write_config_mapping(path, {"API_KEY": "abc123"})

    assert path.stat().st_mode & 0o077 == 0
    assert path.parent.stat().st_mode & 0o077 == 0


def test_read_hardens_permissions_of_an_existing_legacy_database(tmp_path: Path) -> None:
    path = tmp_path / "config.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute("INSERT INTO config (key, value) VALUES ('API_KEY', 'secret')")
    connection.commit()
    connection.close()
    path.chmod(0o644)

    assert read_config_mapping(path)["API_KEY"] == "secret"
    assert path.stat().st_mode & 0o077 == 0


def test_sqlite_sidecars_are_restricted_when_present(tmp_path: Path) -> None:
    path = tmp_path / "config.db"
    candidates = [path, Path(f"{path}-wal"), Path(f"{path}-shm")]
    for candidate in candidates:
        candidate.write_bytes(b"")
        candidate.chmod(0o644)

    config_store_module._secure_database_files(path)

    assert all(candidate.stat().st_mode & 0o077 == 0 for candidate in candidates)


def test_import_dotenv_into_db_skips_comments_and_blank_values(tmp_path: Path) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "RTSP_PASSWORD=s3cr3t\n# a comment line\nAPI_KEY=\nOTHER_KEY=value2\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "config.db"

    count = import_dotenv_into_db(dotenv_path, db_path)

    assert count == 2
    assert read_config_mapping(db_path) == {
        "RTSP_PASSWORD": "s3cr3t",
        "OTHER_KEY": "value2",
    }


def test_import_dotenv_into_db_returns_zero_for_only_comments_and_blanks(tmp_path: Path) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "# nothing to see here\nAPI_KEY=\nOTHER_KEY=   \n",
        encoding="utf-8",
    )
    db_path = tmp_path / "config.db"

    count = import_dotenv_into_db(dotenv_path, db_path)

    assert count == 0
    assert not db_path.exists()


def test_users_only_sqlite_is_not_considered_initialized(tmp_path: Path) -> None:
    path = tmp_path / "config.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()

    assert not is_config_initialized(path)
    assert read_config_mapping(path) == {}
    assert read_config_revision(path) == 0


def test_initialize_is_one_time_and_never_overwrites_edits(tmp_path: Path) -> None:
    path = tmp_path / "config.db"

    first_revision = initialize_config_mapping(path, {"POLL_INTERVAL_SECONDS": "30"})
    mutate_config_mapping(path, values={"POLL_INTERVAL_SECONDS": "8"})
    second_revision = initialize_config_mapping(path, {"POLL_INTERVAL_SECONDS": "99"})

    assert first_revision == 1
    assert second_revision == 2
    assert read_config_mapping(path)["POLL_INTERVAL_SECONDS"] == "8"


def test_atomic_mutation_rejects_stale_revision_and_preserves_winner(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.db"
    initialize_config_mapping(path, {"POLL_INTERVAL_SECONDS": "30"})
    _, revision = read_config_snapshot(path)

    winner_revision = mutate_config_mapping(
        path,
        values={"POLL_INTERVAL_SECONDS": "10"},
        expected_revision=revision,
    )
    with pytest.raises(ConfigRevisionConflict):
        mutate_config_mapping(
            path,
            values={"POLL_INTERVAL_SECONDS": "2"},
            expected_revision=revision,
        )

    mapping, final_revision = read_config_snapshot(path)
    assert winner_revision == revision + 1
    assert final_revision == winner_revision
    assert mapping["POLL_INTERVAL_SECONDS"] == "10"


def test_failed_candidate_validation_rolls_back_without_revision_change(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.db"
    initialize_config_mapping(path, {"POLL_INTERVAL_SECONDS": "30"})
    before_mapping, before_revision = read_config_snapshot(path)

    def reject(_candidate) -> None:
        raise ValueError("invalid")

    with pytest.raises(ValueError, match="invalid"):
        mutate_config_mapping(
            path,
            values={"POLL_INTERVAL_SECONDS": "-1"},
            validator=reject,
        )

    assert read_config_snapshot(path) == (before_mapping, before_revision)
