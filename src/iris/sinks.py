from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pymongo

logger = logging.getLogger("iris.events")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")
_SAFE_EVENT_ID = re.compile(r"^[A-Za-z0-9_-]{8,80}$")


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


def _log_safe_summary(event: dict[str, Any]) -> None:
    analysis = event.get("analysis")
    safe_log = {
        "event_type": event.get("event_type"),
        "camera_id": event.get("camera_id"),
        "captured_at": event.get("captured_at"),
        "risk_score": analysis.get("risk_score") if isinstance(analysis, dict) else None,
        "alert": analysis.get("alert") if isinstance(analysis, dict) else None,
        "severity": analysis.get("severity") if isinstance(analysis, dict) else None,
        "semantic_event": (analysis.get("event") if isinstance(analysis, dict) else None),
    }
    logger.info(
        "%s",
        json.dumps(safe_log, ensure_ascii=False, separators=(",", ":")),
    )


class EventSink:
    def __init__(
        self,
        jsonl_path: Path | None = None,
        *,
        max_bytes: int = 0,
        backup_count: int = 5,
    ) -> None:
        self._path = jsonl_path
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._lock = threading.Lock()
        if self._path is not None:
            _secure_directory(self._path.parent)
            if self._path.exists():
                try:
                    self._path.chmod(0o600)
                except OSError:
                    logger.warning("No se pudieron restringir los permisos de %s.", self._path)

    def publish(self, event: dict[str, Any]) -> None:
        serialized = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        _log_safe_summary(event)
        if self._path is None:
            return
        with self._lock:
            self._rotate_if_needed(len(serialized.encode("utf-8")) + 1)
            descriptor = os.open(
                self._path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o600,
            )
            with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
                stream.write(serialized)
                stream.write("\n")

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        if (
            self._path is None
            or self._max_bytes == 0
            or not self._path.exists()
            or self._path.stat().st_size + incoming_bytes <= self._max_bytes
        ):
            return
        for index in range(self._backup_count, 0, -1):
            source = (
                self._path if index == 1 else self._path.with_name(f"{self._path.name}.{index - 1}")
            )
            destination = self._path.with_name(f"{self._path.name}.{index}")
            if destination.exists() and index == self._backup_count:
                destination.unlink()
            if source.exists():
                os.replace(source, destination)


class MongoEventSink:
    def __init__(
        self,
        uri: str,
        database: str,
        collection: str,
        *,
        server_selection_timeout_ms: int = 5_000,
    ) -> None:
        self._client: pymongo.MongoClient = pymongo.MongoClient(
            uri,
            serverSelectionTimeoutMS=server_selection_timeout_ms,
        )
        self._collection = self._client[database][collection]

    def publish(self, event: dict[str, Any]) -> None:
        _log_safe_summary(event)
        document = dict(event)
        document.setdefault("received_at", datetime.now(UTC).isoformat())
        self._collection.insert_one(document)

    def close(self) -> None:
        self._client.close()


class MultiEventSink:
    def __init__(self, sinks: Sequence[Any]) -> None:
        self._sinks = [sink for sink in sinks if sink is not None]

    def publish(self, event: dict[str, Any]) -> None:
        succeeded = False
        last_error: BaseException = RuntimeError(
            "MultiEventSink no tiene sinks configurados para publicar el evento."
        )
        for sink in self._sinks:
            try:
                sink.publish(event)
            except Exception as exc:  # failures per sink must not stop the fan-out
                last_error = exc
                logger.exception(
                    "El sink %s falló al publicar el evento (event_type=%s, camera_id=%s).",
                    type(sink).__name__,
                    event.get("event_type"),
                    event.get("camera_id"),
                )
            else:
                succeeded = True
        if not succeeded:
            raise last_error

    def close(self) -> None:
        for sink in self._sinks:
            closer = getattr(sink, "close", None)
            if callable(closer):
                closer()


class CaptureStore:
    def __init__(
        self,
        directory: Path,
        *,
        enabled: bool,
        retention_days: float = 0,
        max_files_per_camera: int = 0,
    ) -> None:
        self._directory = directory
        self._enabled = enabled
        self._retention_seconds = retention_days * 86_400
        self._max_files_per_camera = max_files_per_camera
        self._lock = threading.Lock()
        if enabled:
            _secure_directory(directory)

    def save(
        self,
        jpeg: bytes,
        *,
        camera_id: str,
        camera_name: str,
        captured_at_compact: str,
        sequence: int,
    ) -> str | None:
        if not self._enabled:
            return None
        with self._lock:
            safe_name = _SAFE_NAME.sub("-", camera_name).strip("-") or camera_id
            camera_dir = self._directory / camera_id
            _secure_directory(camera_dir)
            path = camera_dir / (f"{captured_at_compact}_{safe_name}_frame-{sequence:012d}.jpg")
            descriptor = os.open(
                path,
                os.O_CREAT | os.O_TRUNC | os.O_WRONLY,
                0o600,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(jpeg)
            self._prune(camera_dir)
        return str(path)

    @staticmethod
    def _write_atomic(path: Path, content: bytes) -> None:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            descriptor = os.open(
                temporary,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            with suppress(FileNotFoundError):
                temporary.unlink()

    def save_preview(
        self,
        jpeg: bytes,
        *,
        camera_id: str,
        event_id: str,
    ) -> str | None:
        """Persist the immutable preview paired with one semantic result."""

        if not _SAFE_EVENT_ID.fullmatch(event_id):
            logger.warning("Se rechazó un event_id inválido para %s.", camera_id)
            return None
        try:
            with self._lock:
                camera_dir = self._directory / camera_id
                _secure_directory(camera_dir)
                path = camera_dir / f"preview-{event_id}.jpg"
                self._write_atomic(path, jpeg)
                previews = sorted(
                    camera_dir.glob("preview-*.jpg"),
                    key=lambda candidate: candidate.stat().st_mtime,
                    reverse=True,
                )
                for expired in previews[20:]:
                    expired.unlink()
            return str(path)
        except OSError:
            logger.warning("No se pudo escribir la captura versionada de %s.", camera_id)
            return None

    def save_latest(self, jpeg: bytes, *, camera_id: str) -> bool:
        """Overwrites ``{capture_dir}/{camera_id}/latest.jpg`` unconditionally.

        This is the lightweight operational preview shown by the dashboard
        (the last frame actually sent to the vision model), not the
        severity-gated evidence-retention mechanism in ``save()``: it always
        writes regardless of ``self._enabled`` (``SAVE_CAPTURES=false`` must
        not disable it), keeps exactly one file per camera (always
        overwritten, no timestamp/sequence, no retention/pruning), and must
        never raise -- a failure to write a preview frame must never
        interrupt the analysis pipeline that calls it.
        """
        try:
            with self._lock:
                camera_dir = self._directory / camera_id
                _secure_directory(camera_dir)
                path = camera_dir / "latest.jpg"
                self._write_atomic(path, jpeg)
            return True
        except OSError:
            logger.warning("No se pudo escribir el frame más reciente de %s.", camera_id)
            return False

    def _prune(self, camera_dir: Path) -> None:
        if self._retention_seconds == 0 and self._max_files_per_camera == 0:
            return
        files: list[tuple[Path, float]] = []
        for path in camera_dir.glob("*.jpg"):
            if path.name == "latest.jpg" or path.name.startswith("preview-"):
                continue
            try:
                files.append((path, path.stat().st_mtime))
            except OSError:
                logger.warning("No se pudo inspeccionar %s para retención.", path)
        files.sort(key=lambda item: item[1], reverse=True)
        cutoff = time.time() - self._retention_seconds
        for position, (path, modified_at) in enumerate(files):
            expired = self._retention_seconds > 0 and modified_at < cutoff
            over_limit = self._max_files_per_camera > 0 and position >= self._max_files_per_camera
            if not expired and not over_limit:
                continue
            try:
                path.unlink()
            except OSError:
                logger.warning("No se pudo eliminar la captura expirada %s.", path)
