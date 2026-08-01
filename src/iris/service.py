from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from iris.image import encode_jpeg, resize_with_letterbox, variation_index_percent
from iris.models import (
    SEVERITY_ORDER,
    AnalysisResult,
    CameraConfig,
    Frame,
    FrameSnapshot,
    ServiceConfig,
)
from iris.notifications import TelegramNotifier
from iris.rtsp import LatestFrameReader
from iris.sinks import CaptureStore, EventSink, MongoEventSink, MultiEventSink

logger = logging.getLogger(__name__)
_INITIAL_FRAME_RETRY_SECONDS = 1.0


class Analyzer(Protocol):
    def analyze(
        self,
        jpeg: bytes,
        *,
        camera: CameraConfig,
        captured_at: str,
    ) -> AnalysisResult: ...

    def close(self) -> None: ...


@dataclass(slots=True)
class _CameraState:
    camera: CameraConfig
    reader: LatestFrameReader
    next_poll_at: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_seen_sequence: int | None = None
    pending: _PendingCandidate | None = None
    in_flight: bool = False
    has_captured_frame: bool = False
    last_analyzed_frame: Frame | None = None
    last_severity: str | None = None


@dataclass(frozen=True, slots=True)
class _PendingCandidate:
    snapshot: FrameSnapshot
    frame: Frame


@dataclass(frozen=True, slots=True)
class _AnalysisJob:
    event_id: str
    camera: CameraConfig
    snapshot: FrameSnapshot
    jpeg: bytes
    trigger: str
    latest_available: bool


def _meets_severity_threshold(severity: object, threshold: str) -> bool:
    if not isinstance(severity, str) or severity not in SEVERITY_ORDER:
        return False
    return SEVERITY_ORDER.index(severity) >= SEVERITY_ORDER.index(threshold)


def _notification_caption(job: _AnalysisJob, result: AnalysisResult) -> str:
    risk_score = result.data.get("risk_score")
    severity = result.data.get("severity")
    summary = result.data.get("summary") or ""
    return (
        f"{job.camera.name} ({job.camera.identifier})\n"
        f"Severidad: {severity} · Riesgo: {risk_score}/100\n"
        f"{summary}"
    )


def _advance_schedule(current: float, now: float, interval: float) -> float:
    """Return the next scheduled tick after ``current``, ``interval`` seconds apart.

    Pure arithmetic extracted out of ``run()``'s loop so it can be unit tested
    without driving the real blocking loop. If the schedule fell behind (we're
    already at or past what would be the next tick), it catches up from
    ``now`` instead of spiraling into a backlog of immediately-due ticks.
    """

    next_tick = current + interval
    if next_tick <= now:
        next_tick = now + interval
    return next_tick


class _SlidingWindowRateLimiter:
    def __init__(self, calls_per_minute: int) -> None:
        self._limit = calls_per_minute
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    def try_acquire(self, now: float) -> bool:
        if self._limit == 0:
            return True
        cutoff = now - 60.0
        with self._lock:
            while self._timestamps and self._timestamps[0] <= cutoff:
                self._timestamps.popleft()
            if len(self._timestamps) >= self._limit:
                return False
            self._timestamps.append(now)
            return True


class MonitoringService:
    def __init__(
        self,
        config: ServiceConfig,
        analyzer: Analyzer,
        *,
        readers: list[LatestFrameReader] | None = None,
        event_sink: EventSink | None = None,
        capture_store: CaptureStore | None = None,
        notifier: TelegramNotifier | None = None,
    ) -> None:
        self._config = config
        self._analyzer = analyzer
        if notifier is not None:
            self._notifier = notifier
        elif config.telegram_enabled and config.telegram_bot_token and config.telegram_chat_id:
            self._notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)
        else:
            self._notifier = None
        if event_sink is not None:
            self._events = event_sink
        else:
            jsonl_sink = EventSink(
                config.events_jsonl_path,
                max_bytes=config.events_max_bytes,
                backup_count=config.events_backup_count,
            )
            if config.mongo_uri is not None:
                mongo_sink = MongoEventSink(
                    config.mongo_uri,
                    config.mongo_database,
                    config.mongo_detection_collection,
                )
                self._events = MultiEventSink([jsonl_sink, mongo_sink])
            else:
                self._events = jsonl_sink
        selected_readers = (
            readers
            if readers is not None
            else [
                LatestFrameReader(
                    camera,
                    reconnect_interval_seconds=config.reconnect_interval_seconds,
                    open_timeout_ms=config.rtsp_open_timeout_ms,
                    read_timeout_ms=config.rtsp_read_timeout_ms,
                    rtsp_transport=config.rtsp_transport,
                    status_callback=self._publish_status,
                )
                for camera in config.cameras
            ]
        )
        if len(selected_readers) != len(config.cameras):
            raise ValueError("Debe existir exactamente un reader por cámara.")
        self._states = [
            _CameraState(camera=camera, reader=reader)
            for camera, reader in zip(config.cameras, selected_readers, strict=True)
        ]
        self._captures = capture_store or CaptureStore(
            config.capture_dir,
            enabled=config.save_captures,
            retention_days=config.capture_retention_days,
            max_files_per_camera=config.capture_max_files_per_camera,
        )
        self._executor = ThreadPoolExecutor(
            # El worker sigue siendo único como segunda barrera. Además,
            # _analysis_in_flight evita enviar trabajos congelados a su cola:
            # los demás frames permanecen reemplazables en cada cámara.
            max_workers=1,
            thread_name_prefix="semantic-analysis",
        )
        self._dispatch_lock = threading.Lock()
        self._analysis_in_flight = False
        self._next_dispatch_position = 0
        self._rate_limiter = _SlidingWindowRateLimiter(config.max_api_calls_per_minute)
        self._stop_event = threading.Event()
        self._started = False
        self._closed = False

    def request_stop(self) -> None:
        self._stop_event.set()
        cancel = getattr(self._analyzer, "cancel", None)
        if callable(cancel):
            cancel()
        # Señalamos todos los lectores antes de esperar por cualquiera de
        # ellos. Así sus reads FFmpeg desbloquean en paralelo durante una
        # recarga de configuración o un cierre.
        for state in self._states:
            request_reader_stop = getattr(state.reader, "request_stop", None)
            if callable(request_reader_stop):
                request_reader_stop()

    def run(self) -> None:
        try:
            self.start()
            while not self._stop_event.is_set():
                now = time.monotonic()
                for state in self._states:
                    if now >= state.next_poll_at:
                        waiting_for_first_frame = not state.has_captured_frame
                        try:
                            self._poll_camera(state)
                        except Exception:
                            logger.exception("No se pudo procesar %s.", state.camera.identifier)
                        if waiting_for_first_frame and not state.has_captured_frame:
                            # El reader arranca en paralelo y puede tardar unos
                            # segundos en abrir RTSP. No castigamos ese warm-up
                            # con una espera completa del intervalo configurado.
                            state.next_poll_at = now + min(
                                _INITIAL_FRAME_RETRY_SECONDS,
                                state.camera.poll_interval_seconds,
                            )
                        elif waiting_for_first_frame:
                            # El intervalo mínimo se cuenta desde la primera
                            # captura real, no desde el intento vacío inicial.
                            state.next_poll_at = now + state.camera.poll_interval_seconds
                        else:
                            state.next_poll_at = _advance_schedule(
                                state.next_poll_at,
                                now,
                                state.camera.poll_interval_seconds,
                            )
                next_tick = min((state.next_poll_at for state in self._states), default=now)
                self._stop_event.wait(max(0.0, next_tick - time.monotonic()))
        finally:
            self.close()

    def start(self) -> None:
        if self._started:
            return
        if self._closed:
            raise RuntimeError("MonitoringService es de un solo uso y ya fue cerrado.")
        self._started = True
        now = time.monotonic()
        camera_count = len(self._states)
        stagger_window = min(
            (state.camera.poll_interval_seconds for state in self._states),
            default=0.0,
        )
        stagger_step = stagger_window / camera_count if camera_count > 1 else 0.0
        for position, state in enumerate(self._states):
            state.reader.start()
            # Repartir el primer ciclo dentro del intervalo más corto evita
            # ráfagas simultáneas al iniciar, sin alterar la cadencia propia
            # que mantiene cada cámara después de ese primer turno.
            state.next_poll_at = now + (position * stagger_step)
        logger.info(
            "IRIS iniciado con %d cámara(s), polling por cámara >=10s, resolución "
            "%dx%d, análisis Alibaba serializado y desfase inicial %.2fs.",
            len(self._states),
            self._config.frame_width,
            self._config.frame_height,
            stagger_step,
        )

    def poll_once(self) -> None:
        for state in self._states:
            try:
                self._poll_camera(state)
            except Exception:
                logger.exception("No se pudo procesar %s.", state.camera.identifier)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop_event.set()
        cancel = getattr(self._analyzer, "cancel", None)
        if callable(cancel):
            cancel()
        readers_stopped = True
        for state in self._states:
            if state.reader.stop() is False:
                readers_stopped = False
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._analyzer.close()
        if self._notifier is not None:
            self._notifier.close()
        close_events = getattr(self._events, "close", None)
        if callable(close_events):
            close_events()
        self._started = False
        logger.info("IRIS detenido correctamente.")
        if not readers_stopped:
            raise RuntimeError(
                "Uno o más lectores RTSP no terminaron; no es seguro iniciar otra generación."
            )

    def _poll_camera(self, state: _CameraState) -> None:
        snapshot = state.reader.latest()
        if snapshot is None:
            logger.debug("%s aún no tiene un frame.", state.camera.identifier)
            self._try_schedule_pending(state)
            return
        duplicate_snapshot = False
        with state.lock:
            if (
                state.last_seen_sequence is not None
                and snapshot.sequence <= state.last_seen_sequence
            ):
                logger.debug(
                    "%s aún no entrega un frame RTSP nuevo (secuencia %d).",
                    state.camera.identifier,
                    snapshot.sequence,
                )
                duplicate_snapshot = True
            else:
                state.last_seen_sequence = snapshot.sequence
        if duplicate_snapshot:
            self._try_schedule_pending(state)
            return
        age = (datetime.now(UTC) - snapshot.captured_at).total_seconds()
        if age > self._config.frame_stale_after_seconds:
            logger.warning(
                "Se omitió un frame obsoleto de %s (edad %.1fs).",
                state.camera.identifier,
                age,
            )
            self._try_schedule_pending(state)
            return

        frame = resize_with_letterbox(
            snapshot.frame,
            self._config.frame_width,
            self._config.frame_height,
        )
        candidate = _PendingCandidate(
            snapshot=snapshot,
            frame=frame,
        )
        with state.lock:
            if (
                state.pending is None
                or candidate.snapshot.sequence > state.pending.snapshot.sequence
            ):
                state.pending = candidate
        self._try_schedule_pending(state)

    def _last_severity_allows_skip(self, state: _CameraState) -> bool:
        """True only once a camera has a *confirmed* low-risk reading.

        An unknown/never-analyzed state (``None``) never allows a skip: we
        only trust variation gating once we know for a fact the scene was
        calm. A last severity of medium+ always forces re-analysis regardless
        of pixel variation, so a stationary emergency (a person motionless
        after a fall, an unattended fire that stopped spreading, an intruder
        standing still) never stops getting re-checked just because the frame
        looks visually similar to the previous one.
        """

        severity = state.last_severity
        if not isinstance(severity, str) or severity not in SEVERITY_ORDER:
            return False
        return not _meets_severity_threshold(severity, "medium")

    def _should_skip_low_variation(
        self, state: _CameraState, candidate: _PendingCandidate
    ) -> tuple[bool, float | None]:
        if self._config.change_threshold_percent <= 0 or state.last_analyzed_frame is None:
            return False, None
        if not self._last_severity_allows_skip(state):
            return False, None
        variation = variation_index_percent(
            state.last_analyzed_frame,
            candidate.frame,
            width=self._config.delta_width,
            height=self._config.delta_height,
            pixel_threshold=self._config.pixel_change_threshold,
        )
        return variation < self._config.change_threshold_percent, variation

    def _handle_skipped_candidate(
        self,
        state: _CameraState,
        candidate: _PendingCandidate,
        variation: float | None,
    ) -> None:
        """Keep the operational preview fresh without spending an Alibaba call."""

        try:
            jpeg = encode_jpeg(candidate.frame, quality=self._config.jpeg_quality)
            self._captures.save_latest(jpeg, camera_id=state.camera.identifier)
        except Exception:
            logger.exception(
                "No se pudo guardar la captura operativa de %s tras omitir el análisis.",
                state.camera.identifier,
            )
            return
        state.has_captured_frame = True
        logger.debug(
            "Se omitió el análisis de %s: variación %.2f%% bajo el umbral %.2f%%.",
            state.camera.identifier,
            variation if variation is not None else 0.0,
            self._config.change_threshold_percent,
        )
        self._publish_safely(
            {
                "event_type": "analysis.skipped",
                "camera_id": state.camera.identifier,
                "camera_name": state.camera.name,
                "captured_at": candidate.snapshot.captured_at.isoformat(),
                "completed_at": datetime.now(UTC).isoformat(),
                "trigger": "poll",
                "variation_index_percent": variation,
                "change_threshold_percent": self._config.change_threshold_percent,
                "config_revision": self._config.config_revision,
            }
        )

    def _try_schedule_pending(self, state: _CameraState) -> bool:
        if self._stop_event.is_set():
            return False
        now = time.monotonic()
        should_skip = False
        skip_variation: float | None = None
        candidate: _PendingCandidate | None = None
        with self._dispatch_lock:
            # Cero cola interna: mientras Alibaba trabaja, cada cámara conserva
            # su candidato más nuevo en _CameraState.pending.
            if self._analysis_in_flight:
                return False
            with state.lock:
                if state.in_flight or state.pending is None:
                    return False
                candidate = state.pending
                age = (datetime.now(UTC) - candidate.snapshot.captured_at).total_seconds()
                if age > self._config.frame_stale_after_seconds:
                    state.pending = None
                    logger.warning(
                        "Se descartó el frame pendiente obsoleto de %s (edad %.1fs).",
                        state.camera.identifier,
                        age,
                    )
                    return False
                should_skip, skip_variation = self._should_skip_low_variation(state, candidate)
                if should_skip:
                    state.pending = None
                else:
                    if not self._rate_limiter.try_acquire(now):
                        logger.debug(
                            "Límite global de API alcanzado; %s queda pendiente.",
                            state.camera.identifier,
                        )
                        return False
                    state.pending = None
                    state.in_flight = True
                    state.last_analyzed_frame = candidate.frame
            if not should_skip:
                self._analysis_in_flight = True
                position = next(
                    index
                    for index, camera_state in enumerate(self._states)
                    if camera_state is state
                )
                self._next_dispatch_position = (position + 1) % len(self._states)

        if should_skip:
            self._handle_skipped_candidate(state, candidate, skip_variation)
            return False

        try:
            jpeg = encode_jpeg(candidate.frame, quality=self._config.jpeg_quality)
            latest_result = self._captures.save_latest(
                jpeg,
                camera_id=state.camera.identifier,
            )
            job = _AnalysisJob(
                event_id=uuid.uuid4().hex,
                camera=state.camera,
                snapshot=candidate.snapshot,
                jpeg=jpeg,
                trigger="poll",
                latest_available=latest_result is not False,
            )
            future = self._executor.submit(self._execute_analysis, job)
            state.has_captured_frame = True
        except Exception:
            with state.lock:
                state.in_flight = False
                if (
                    state.pending is None
                    or candidate.snapshot.sequence > state.pending.snapshot.sequence
                ):
                    state.pending = candidate
            with self._dispatch_lock:
                self._analysis_in_flight = False
            raise
        future.add_done_callback(
            lambda completed, camera_state=state, analysis_job=job: self._analysis_done(
                camera_state,
                analysis_job,
                completed,
            )
        )
        return True

    def _try_schedule_next_pending(self) -> None:
        """Dispatch one fresh candidate in round-robin order, never a frozen queue."""

        if self._stop_event.is_set() or not self._states:
            return
        with self._dispatch_lock:
            if self._analysis_in_flight:
                return
            start = self._next_dispatch_position
        for offset in range(len(self._states)):
            state = self._states[(start + offset) % len(self._states)]
            if self._try_schedule_pending(state):
                return

    def _execute_analysis(self, job: _AnalysisJob) -> AnalysisResult:
        return self._analyzer.analyze(
            job.jpeg,
            camera=job.camera,
            captured_at=job.snapshot.captured_at.isoformat(),
        )

    def _analysis_done(
        self,
        state: _CameraState,
        job: _AnalysisJob,
        future: Future[AnalysisResult],
    ) -> None:
        completed_at = datetime.now(UTC)
        result: AnalysisResult | None = None
        try:
            result = future.result()
        except Exception as exc:
            logger.exception(
                "Falló el análisis semántico de %s.",
                job.camera.identifier,
                exc_info=exc,
            )
            self._publish_safely(
                {
                    "event_type": "analysis.failed",
                    "event_id": job.event_id,
                    "camera_id": job.camera.identifier,
                    "camera_name": job.camera.name,
                    "captured_at": job.snapshot.captured_at.isoformat(),
                    "completed_at": completed_at.isoformat(),
                    "resolution": {
                        "width": self._config.frame_width,
                        "height": self._config.frame_height,
                    },
                    "trigger": job.trigger,
                    "snapshot_path": None,
                    "preview_path": None,
                    "preview_available": job.latest_available,
                    "config_revision": self._config.config_revision,
                    "error": type(exc).__name__,
                }
            )
        else:
            save_preview = getattr(self._captures, "save_preview", None)
            preview_path = (
                save_preview(
                    job.jpeg,
                    camera_id=job.camera.identifier,
                    event_id=job.event_id,
                )
                if callable(save_preview)
                else None
            )
            preview_available = preview_path is not None or job.latest_available
            severity = result.data.get("severity")
            if isinstance(severity, str) and severity in SEVERITY_ORDER:
                with state.lock:
                    state.last_severity = severity
            if self._notifier is not None and _meets_severity_threshold(
                severity, job.camera.notification_threshold
            ):
                self._notifier.send_photo(job.jpeg, caption=_notification_caption(job, result))
            if _meets_severity_threshold(severity, self._config.save_image_min_severity):
                snapshot_path = self._captures.save(
                    job.jpeg,
                    camera_id=job.camera.identifier,
                    camera_name=job.camera.name,
                    captured_at_compact=job.snapshot.captured_at.strftime("%Y%m%dT%H%M%S.%fZ"),
                    sequence=job.snapshot.sequence,
                )
            else:
                snapshot_path = None
            event = {
                "event_type": "analysis.completed",
                "event_id": job.event_id,
                "camera_id": job.camera.identifier,
                "camera_name": job.camera.name,
                "captured_at": job.snapshot.captured_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "resolution": {
                    "width": self._config.frame_width,
                    "height": self._config.frame_height,
                },
                "trigger": job.trigger,
                "snapshot_path": snapshot_path,
                "preview_path": preview_path,
                "preview_available": preview_available,
                "config_revision": self._config.config_revision,
                "model": result.model,
                "request_id": result.request_id,
                "analysis": result.data,
                "usage": result.usage,
            }
            try:
                self._events.publish(event)
            except Exception:
                logger.exception(
                    "El análisis de %s terminó, pero el evento no pudo persistirse.",
                    job.camera.identifier,
                )
            else:
                logger.debug(
                    "Análisis %s persistido para %s.",
                    job.event_id,
                    job.camera.identifier,
                )
        finally:
            with state.lock:
                state.in_flight = False
            with self._dispatch_lock:
                self._analysis_in_flight = False
            if not self._stop_event.is_set():
                try:
                    self._try_schedule_next_pending()
                except Exception:
                    logger.exception(
                        "No se pudo programar el siguiente frame pendiente tras %s.",
                        job.camera.identifier,
                    )

    def _publish_safely(self, event: dict[str, object]) -> None:
        try:
            self._events.publish(event)
        except Exception:
            logger.exception(
                "No se pudo persistir el evento %s de %s.",
                event.get("event_type"),
                event.get("camera_id"),
            )

    def _publish_status(self, event: dict[str, object]) -> None:
        enriched = dict(event)
        enriched.setdefault("config_revision", self._config.config_revision)
        self._publish_safely(enriched)
