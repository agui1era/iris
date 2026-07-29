from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import bcrypt

logger = logging.getLogger("iris.users_store")

_VALID_ROLES = ("admin", "normal")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'normal')),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
)
"""

_SELECT_COLUMNS = "id, username, role, is_active, created_at"


class UsersStoreError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class User:
    id: int
    username: str
    role: str
    is_active: bool
    created_at: str


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


def _connect(path: Path) -> sqlite3.Connection:
    _secure_directory(path.parent)
    is_new = not path.exists()
    connection = sqlite3.connect(path)
    connection.execute(_CREATE_TABLE)
    connection.commit()
    if is_new:
        try:
            path.chmod(0o600)
        except OSError:
            logger.warning("No se pudieron restringir los permisos de %s.", path)
    return connection


def _restrict_file(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        logger.warning("No se pudieron restringir los permisos de %s.", path)


def _validate_role(role: str) -> None:
    if role not in _VALID_ROLES:
        raise UsersStoreError(f"Rol inválido: {role!r}. Usa 'admin' o 'normal'.")


def _row_to_user(row: tuple[int, str, str, int, str]) -> User:
    id_, username, role, is_active, created_at = row
    return User(
        id=id_, username=username, role=role, is_active=bool(is_active), created_at=created_at
    )


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_user(path: Path, username: str, password: str, role: str) -> User:
    _validate_role(role)
    password_hash = hash_password(password)
    created_at = datetime.now(UTC).isoformat()
    connection = _connect(path)
    try:
        try:
            cursor = connection.execute(
                "INSERT INTO users (username, password_hash, role, is_active, created_at) "
                "VALUES (?, ?, ?, 1, ?)",
                (username, password_hash, role, created_at),
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise UsersStoreError(f"El usuario '{username}' ya existe.") from exc
        row = connection.execute(
            f"SELECT {_SELECT_COLUMNS} FROM users WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    finally:
        connection.close()
    _restrict_file(path)
    return _row_to_user(row)


def verify_credentials(path: Path, username: str, password: str) -> User | None:
    connection = _connect(path)
    try:
        row = connection.execute(
            f"SELECT {_SELECT_COLUMNS}, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    user = _row_to_user(row[:-1])
    password_hash = row[-1]
    if not user.is_active:
        return None
    if not verify_password(password, password_hash):
        return None
    return user


def get_user(path: Path, username: str) -> User | None:
    connection = _connect(path)
    try:
        row = connection.execute(
            f"SELECT {_SELECT_COLUMNS} FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    finally:
        connection.close()
    return _row_to_user(row) if row is not None else None


def list_users(path: Path) -> list[User]:
    connection = _connect(path)
    try:
        rows = connection.execute(
            f"SELECT {_SELECT_COLUMNS} FROM users ORDER BY username"
        ).fetchall()
    finally:
        connection.close()
    return [_row_to_user(row) for row in rows]


def set_role(path: Path, username: str, role: str) -> None:
    _validate_role(role)
    connection = _connect(path)
    try:
        cursor = connection.execute(
            "UPDATE users SET role = ? WHERE username = ?", (role, username)
        )
        connection.commit()
    finally:
        connection.close()
    if cursor.rowcount == 0:
        raise UsersStoreError(f"El usuario '{username}' no existe.")
    _restrict_file(path)


def set_active(path: Path, username: str, is_active: bool) -> None:
    connection = _connect(path)
    try:
        cursor = connection.execute(
            "UPDATE users SET is_active = ? WHERE username = ?",
            (1 if is_active else 0, username),
        )
        connection.commit()
    finally:
        connection.close()
    if cursor.rowcount == 0:
        raise UsersStoreError(f"El usuario '{username}' no existe.")
    _restrict_file(path)
