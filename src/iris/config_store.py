from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values

logger = logging.getLogger("iris.config_store")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""
_CREATE_STATE_TABLE = """
CREATE TABLE IF NOT EXISTS config_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    initialized INTEGER NOT NULL DEFAULT 0 CHECK (initialized IN (0, 1)),
    desired_revision INTEGER NOT NULL DEFAULT 0 CHECK (desired_revision >= 0),
    updated_at TEXT
)
"""
_SQLITE_FILE_SUFFIXES = ("", "-wal", "-shm")


class ConfigRevisionConflict(RuntimeError):
    def __init__(self, expected: int, current: int) -> None:
        super().__init__(
            f"La configuración cambió mientras editabas "
            f"(revisión esperada {expected}, actual {current})."
        )
        self.expected = expected
        self.current = current


def _secure_directory(path: Path) -> None:
    existed = path.exists()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not existed:
        try:
            path.chmod(0o700)
        except OSError:
            logger.warning("No se pudieron restringir los permisos de %s.", path)
    elif path.stat().st_mode & 0o077:
        logger.warning(
            "El directorio existente %s tiene permisos amplios; usa un subdirectorio privado.",
            path,
        )


def _secure_database_files(path: Path) -> None:
    """Restrict the SQLite database and any existing WAL sidecars."""

    for suffix in _SQLITE_FILE_SUFFIXES:
        candidate = Path(f"{path}{suffix}")
        try:
            candidate.chmod(0o600)
        except FileNotFoundError:
            continue
        except OSError:
            logger.warning("No se pudieron restringir los permisos de %s.", candidate)


def _close_connection(connection: sqlite3.Connection, path: Path) -> None:
    try:
        connection.close()
    finally:
        # SQLite may create or retain WAL/SHM files during any read or write.
        _secure_database_files(path)


def _connect(path: Path) -> sqlite3.Connection:
    _secure_directory(path.parent)
    # Harden legacy databases and sidecars before SQLite reads their contents.
    _secure_database_files(path)
    connection = sqlite3.connect(path, timeout=5.0)
    try:
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute(_CREATE_TABLE)
        connection.execute(_CREATE_STATE_TABLE)
        connection.execute(
            """
            INSERT OR IGNORE INTO config_state
                (singleton, initialized, desired_revision, updated_at)
            VALUES (1, 0, 0, NULL)
            """
        )
        # Compatibilidad con bases creadas por versiones anteriores: si ya había
        # filas en ``config`` pero aún no existía ``config_state``, ese store sí
        # estaba inicializado y debe conservar precedencia sobre el entorno.
        has_legacy_config = connection.execute(
            "SELECT EXISTS(SELECT 1 FROM config LIMIT 1)"
        ).fetchone()[0]
        if has_legacy_config:
            connection.execute(
                """
                UPDATE config_state
                SET initialized = 1,
                    desired_revision = CASE
                        WHEN desired_revision = 0 THEN 1
                        ELSE desired_revision
                    END,
                    updated_at = COALESCE(updated_at, ?)
                WHERE singleton = 1
                """,
                (datetime.now(UTC).isoformat(),),
            )
        connection.commit()
        # Enabling WAL can create the sidecars while the connection is open.
        _secure_database_files(path)
    except Exception:
        _close_connection(connection, path)
        raise
    return connection


def read_config_mapping(path: Path) -> dict[str, str]:
    connection = _connect(path)
    try:
        rows = connection.execute("SELECT key, value FROM config").fetchall()
    finally:
        _close_connection(connection, path)
    return dict(rows)


def is_config_initialized(path: Path) -> bool:
    if not path.exists():
        return False
    connection = _connect(path)
    try:
        row = connection.execute(
            "SELECT initialized FROM config_state WHERE singleton = 1"
        ).fetchone()
    finally:
        _close_connection(connection, path)
    return bool(row and row[0])


def read_config_revision(path: Path) -> int:
    if not path.exists():
        return 0
    connection = _connect(path)
    try:
        row = connection.execute(
            "SELECT desired_revision FROM config_state WHERE singleton = 1"
        ).fetchone()
    finally:
        _close_connection(connection, path)
    return int(row[0]) if row else 0


def read_config_snapshot(path: Path) -> tuple[dict[str, str], int]:
    connection = _connect(path)
    try:
        connection.execute("BEGIN")
        rows = connection.execute("SELECT key, value FROM config").fetchall()
        row = connection.execute(
            "SELECT desired_revision FROM config_state WHERE singleton = 1"
        ).fetchone()
        connection.commit()
    finally:
        _close_connection(connection, path)
    return dict(rows), int(row[0]) if row else 0


def mutate_config_mapping(
    path: Path,
    *,
    values: Mapping[str, str] | None = None,
    delete_keys: Iterable[str] = (),
    expected_revision: int | None = None,
    validator: Callable[[Mapping[str, str]], object] | None = None,
) -> int:
    """Atomically validate and apply a configuration mutation.

    Validation receives the complete candidate mapping while an
    ``IMMEDIATE`` transaction is held. A failed validator or stale expected
    revision rolls the transaction back, so callers never need a
    write/validate/manual-rollback sequence.
    """

    updates = dict(values or {})
    deletions = set(delete_keys)
    connection = _connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        state = connection.execute(
            """
            SELECT initialized, desired_revision
            FROM config_state
            WHERE singleton = 1
            """
        ).fetchone()
        initialized, current_revision = (
            (bool(state[0]), int(state[1])) if state is not None else (False, 0)
        )
        if expected_revision is not None and expected_revision != current_revision:
            raise ConfigRevisionConflict(expected_revision, current_revision)

        rows = connection.execute("SELECT key, value FROM config").fetchall()
        current = dict(rows)
        candidate = dict(current)
        for key in deletions:
            candidate.pop(key, None)
        candidate.update(updates)

        if validator is not None:
            validator(candidate)

        if candidate == current:
            connection.commit()
            return current_revision

        if deletions:
            connection.executemany(
                "DELETE FROM config WHERE key = ?",
                [(key,) for key in deletions],
            )
        if updates:
            connection.executemany(
                """
                INSERT INTO config (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                list(updates.items()),
            )

        new_revision = current_revision + 1
        connection.execute(
            """
            UPDATE config_state
            SET initialized = 1,
                desired_revision = ?,
                updated_at = ?
            WHERE singleton = 1
            """,
            (new_revision, datetime.now(UTC).isoformat()),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        _close_connection(connection, path)
    return new_revision


def initialize_config_mapping(path: Path, values: Mapping[str, str]) -> int:
    """Seed a dynamic config exactly once and return its revision.

    API and monitor may start concurrently. ``BEGIN IMMEDIATE`` plus the
    second initialized check ensures only the first process seeds; later
    starts never overwrite edits already made in the dashboard.
    """

    if not values:
        return read_config_revision(path)
    connection = _connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        state = connection.execute(
            """
            SELECT initialized, desired_revision
            FROM config_state
            WHERE singleton = 1
            """
        ).fetchone()
        if state is not None and bool(state[0]):
            connection.commit()
            return int(state[1])
        connection.executemany(
            """
            INSERT INTO config (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            list(values.items()),
        )
        connection.execute(
            """
            UPDATE config_state
            SET initialized = 1,
                desired_revision = 1,
                updated_at = ?
            WHERE singleton = 1
            """,
            (datetime.now(UTC).isoformat(),),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        _close_connection(connection, path)
    return 1


def write_config_mapping(path: Path, values: Mapping[str, str]) -> None:
    if not values:
        return
    mutate_config_mapping(path, values=values)


def delete_config_keys(path: Path, keys: Iterable[str]) -> None:
    """Delete ``keys`` from the config store, if present.

    Deleting a key that does not exist is a silent no-op, matching the
    upsert posture of ``write_config_mapping``: callers use this to roll back
    partially-written keys without needing to check existence first.
    """

    keys = list(keys)
    if not keys:
        return
    mutate_config_mapping(path, delete_keys=keys)


def import_dotenv_into_db(dotenv_path: Path, db_path: Path) -> int:
    parsed = dotenv_values(dotenv_path)
    values = {key: value for key, value in parsed.items() if value is not None and value.strip()}
    if not values:
        return 0
    write_config_mapping(db_path, values)
    return len(values)
