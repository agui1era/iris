from __future__ import annotations

import sqlite3
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ChatThread:
    id: str
    username: str
    camera_id: str
    camera_name: str
    date_from: str
    date_to: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ChatMessage:
    id: int
    thread_id: str
    role: str
    content: str
    created_at: str


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    connection = sqlite3.connect(path, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS chat_threads (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            camera_name TEXT NOT NULL,
            date_from TEXT NOT NULL,
            date_to TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chat_threads_user_updated
            ON chat_threads(username, updated_at DESC);
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chat_messages_thread_id
            ON chat_messages(thread_id, id);
        """
    )
    connection.commit()
    with suppress(OSError):
        path.chmod(0o600)
    return connection


def create_thread(
    path: Path,
    *,
    username: str,
    camera_id: str,
    camera_name: str,
    date_from: str,
    date_to: str,
) -> ChatThread:
    now = datetime.now(UTC).isoformat()
    thread = ChatThread(
        id=uuid.uuid4().hex,
        username=username,
        camera_id=camera_id,
        camera_name=camera_name,
        date_from=date_from,
        date_to=date_to,
        created_at=now,
        updated_at=now,
    )
    with _connect(path) as connection:
        connection.execute(
            """
            INSERT INTO chat_threads
                (id, username, camera_id, camera_name, date_from, date_to, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                thread.id,
                thread.username,
                thread.camera_id,
                thread.camera_name,
                thread.date_from,
                thread.date_to,
                thread.created_at,
                thread.updated_at,
            ),
        )
    return thread


def get_thread(path: Path, thread_id: str, username: str) -> ChatThread | None:
    with _connect(path) as connection:
        row = connection.execute(
            "SELECT * FROM chat_threads WHERE id = ? AND username = ?",
            (thread_id, username),
        ).fetchone()
    return ChatThread(**dict(row)) if row else None


def list_threads(path: Path, username: str, *, limit: int = 30) -> list[ChatThread]:
    with _connect(path) as connection:
        rows = connection.execute(
            """
            SELECT * FROM chat_threads
            WHERE username = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (username, limit),
        ).fetchall()
    return [ChatThread(**dict(row)) for row in rows]


def add_message(path: Path, thread_id: str, role: str, content: str) -> ChatMessage:
    now = datetime.now(UTC).isoformat()
    with _connect(path) as connection:
        cursor = connection.execute(
            "INSERT INTO chat_messages (thread_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (thread_id, role, content, now),
        )
        connection.execute(
            "UPDATE chat_threads SET updated_at = ? WHERE id = ?",
            (now, thread_id),
        )
        message_id = int(cursor.lastrowid)
    return ChatMessage(
        id=message_id,
        thread_id=thread_id,
        role=role,
        content=content,
        created_at=now,
    )


def list_messages(path: Path, thread_id: str) -> list[ChatMessage]:
    with _connect(path) as connection:
        rows = connection.execute(
            "SELECT * FROM chat_messages WHERE thread_id = ? ORDER BY id",
            (thread_id,),
        ).fetchall()
    return [ChatMessage(**dict(row)) for row in rows]
