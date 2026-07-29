from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

import cv2

from iris.models import CameraConfig, Frame, FrameSnapshot

logger = logging.getLogger(__name__)
_STATUS_HEARTBEAT_SECONDS = 30.0


class VideoCaptureLike(Protocol):
    def isOpened(self) -> bool: ...

    def read(self) -> tuple[bool, Frame | None]: ...

    def release(self) -> None: ...


CaptureFactory = Callable[[str, int, int], VideoCaptureLike]
StatusCallback = Callable[[dict[str, object]], None]


def _open_capture(url: str, open_timeout_ms: int, read_timeout_ms: int) -> VideoCaptureLike:
    params: list[int] = []
    open_timeout_property = getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None)
    read_timeout_property = getattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC", None)
    if open_timeout_property is not None:
        params.extend([open_timeout_property, open_timeout_ms])
    if read_timeout_property is not None:
        params.extend([read_timeout_property, read_timeout_ms])
    try:
        capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG, params)
    except TypeError:
        capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    buffer_property = getattr(cv2, "CAP_PROP_BUFFERSIZE", None)
    if capture.isOpened() and buffer_property is not None:
        capture.set(buffer_property, 1)
    return capture


class LatestFrameReader:
    """Continuously drain one stream and retain only its newest frame."""

    def __init__(
        self,
        camera: CameraConfig,
        *,
        reconnect_interval_seconds: float,
        open_timeout_ms: int,
        read_timeout_ms: int,
        rtsp_transport: str,
        capture_factory: CaptureFactory = _open_capture,
        status_callback: StatusCallback | None = None,
    ) -> None:
        self.camera = camera
        self._reconnect_interval_seconds = reconnect_interval_seconds
        self._open_timeout_ms = open_timeout_ms
        self._read_timeout_ms = read_timeout_ms
        self._capture_factory = capture_factory
        self._status_callback = status_callback
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._capture_lock = threading.Lock()
        self._active_capture: VideoCaptureLike | None = None
        self._latest: FrameSnapshot | None = None
        self._sequence = 0
        self._connected: bool | None = None
        self._last_status_report_at: float | None = None
        existing_options = os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS", "")
        options = [
            option
            for option in existing_options.split("|")
            if option and not option.startswith("rtsp_transport;")
        ]
        options.append(f"rtsp_transport;{rtsp_transport}")
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "|".join(options)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"rtsp-{self.camera.identifier}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> bool:
        self.request_stop()
        if self._thread:
            timeout_ms = max(self._open_timeout_ms, self._read_timeout_ms)
            # FFmpeg treats its timeout as a lower-level I/O deadline and can
            # return a little after that exact boundary. Keep a bounded margin
            # so a healthy reader is not reported as leaked during reload.
            self._thread.join(timeout=max(5.0, timeout_ms / 1_000 + 5.0))
            if self._thread.is_alive():
                logger.error(
                    "El lector de %s no terminó dentro del timeout.",
                    self.camera.identifier,
                )
                return False
        return True

    def request_stop(self) -> None:
        """Signal the reader without waiting, so all cameras can unwind in parallel."""

        self._stop_event.set()
        with self._capture_lock:
            capture = self._active_capture
            self._active_capture = None
        if capture is not None:
            capture.release()

    def latest(self) -> FrameSnapshot | None:
        with self._lock:
            if self._latest is None:
                return None
            return FrameSnapshot(
                frame=self._latest.frame.copy(),
                captured_at=self._latest.captured_at,
                sequence=self._latest.sequence,
            )

    def _run(self) -> None:
        while not self._stop_event.is_set():
            capture: VideoCaptureLike | None = None
            try:
                logger.info("Conectando %s (%s).", self.camera.identifier, self.camera.name)
                capture = self._capture_factory(
                    self.camera.rtsp_url,
                    self._open_timeout_ms,
                    self._read_timeout_ms,
                )
                with self._capture_lock:
                    self._active_capture = capture
                if not capture.isOpened():
                    logger.warning("No se pudo abrir %s; se reintentará.", self.camera.identifier)
                    self._set_connection_state(False, reason="open_failed")
                else:
                    logger.info("%s conectada.", self.camera.identifier)
                    self._set_connection_state(True, reason="connected")
                    self._read_until_failure(capture)
            except Exception:
                logger.exception(
                    "Fallo inesperado leyendo %s; se reconectará.",
                    self.camera.identifier,
                )
                self._set_connection_state(False, reason="reader_error")
            finally:
                with self._capture_lock:
                    should_release = capture is not None and self._active_capture is capture
                    if should_release:
                        self._active_capture = None
                if should_release and capture is not None:
                    capture.release()
            self._stop_event.wait(self._reconnect_interval_seconds)

    def _read_until_failure(self, capture: VideoCaptureLike) -> None:
        while not self._stop_event.is_set():
            ok, frame = capture.read()
            if not ok or frame is None or frame.size == 0:
                logger.warning(
                    "Se perdió el stream de %s; iniciando reconexión.",
                    self.camera.identifier,
                )
                if not self._stop_event.is_set():
                    self._set_connection_state(False, reason="read_failed")
                return
            with self._lock:
                self._sequence += 1
                self._latest = FrameSnapshot(
                    frame=frame,
                    captured_at=datetime.now(UTC),
                    sequence=self._sequence,
                )
            self._set_connection_state(True, reason="heartbeat")

    def _set_connection_state(self, connected: bool, *, reason: str) -> None:
        now = time.monotonic()
        same_state = self._connected is connected
        if same_state and (
            not connected
            or (
                self._last_status_report_at is not None
                and now - self._last_status_report_at < _STATUS_HEARTBEAT_SECONDS
            )
        ):
            return
        self._connected = connected
        self._last_status_report_at = now
        if not connected:
            with self._lock:
                self._latest = None
        if self._status_callback is None:
            return
        event = {
            "event_type": "camera.connected" if connected else "camera.offline",
            "camera_id": self.camera.identifier,
            "camera_name": self.camera.name,
            "observed_at": datetime.now(UTC).isoformat(),
            "reason": reason,
        }
        try:
            self._status_callback(event)
        except Exception:
            logger.exception(
                "No se pudo publicar el estado de %s.",
                self.camera.identifier,
            )
