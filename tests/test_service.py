from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import iris.service as service_module
from iris.models import (
    AlibabaConfig,
    AnalysisResult,
    CameraConfig,
    FrameSnapshot,
    ServiceConfig,
)
from iris.service import MonitoringService, _advance_schedule, _SlidingWindowRateLimiter


class SequenceReader:
    def __init__(self, snapshots: list[FrameSnapshot | None]) -> None:
        self.snapshots = list(snapshots)
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def latest(self) -> FrameSnapshot | None:
        if not self.snapshots:
            return None
        return self.snapshots.pop(0)


class FakeAnalyzer:
    def __init__(self, outcomes: list[AnalysisResult | Exception]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    def analyze(
        self,
        jpeg: bytes,
        *,
        camera: CameraConfig,
        captured_at: str,
    ) -> AnalysisResult:
        self.calls.append(
            {
                "jpeg": jpeg,
                "camera": camera,
                "captured_at": captured_at,
            }
        )
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def close(self) -> None:
        self.closed = True


class MemoryEventSink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def publish(self, event: dict[str, Any]) -> None:
        self.events.append(event)


class FakeNotifier:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    def send_photo(self, jpeg: bytes, *, caption: str) -> bool:
        self.calls.append({"jpeg": jpeg, "caption": caption})
        return True

    def close(self) -> None:
        self.closed = True


class MemoryCaptureStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.latest_calls: list[dict[str, Any]] = []
        self.preview_calls: list[dict[str, Any]] = []

    def save(self, jpeg: bytes, **metadata: Any) -> str:
        self.calls.append({"jpeg": jpeg, **metadata})
        return f"memory://{metadata['camera_id']}/{metadata['sequence']}.jpg"

    def save_preview(self, jpeg: bytes, *, camera_id: str, event_id: str) -> str:
        self.preview_calls.append({"jpeg": jpeg, "camera_id": camera_id, "event_id": event_id})
        return f"memory://{camera_id}/preview-{event_id}.jpg"

    def save_latest(self, jpeg: bytes, *, camera_id: str) -> bool:
        self.latest_calls.append({"jpeg": jpeg, "camera_id": camera_id})
        return True


class InlineExecutor:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs
        self.submissions = 0
        self.shutdown_calls: list[dict[str, Any]] = []

    def submit(self, function: Callable[..., AnalysisResult], *args: Any) -> Future:
        self.submissions += 1
        future: Future[AnalysisResult] = Future()
        try:
            future.set_result(function(*args))
        except Exception as exc:
            future.set_exception(exc)
        return future

    def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
        self.shutdown_calls.append({"wait": wait, "cancel_futures": cancel_futures})


class ManualExecutor:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.jobs: list[
            tuple[Callable[..., AnalysisResult], tuple[Any, ...], Future[AnalysisResult]]
        ] = []

    def submit(
        self,
        function: Callable[..., AnalysisResult],
        *args: Any,
    ) -> Future[AnalysisResult]:
        future: Future[AnalysisResult] = Future()
        self.jobs.append((function, args, future))
        return future

    def complete_next(self) -> None:
        function, args, future = self.jobs.pop(0)
        try:
            future.set_result(function(*args))
        except Exception as exc:
            future.set_exception(exc)

    def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
        return None


def make_result(summary: str, *, alert: bool = False, severity: str = "low") -> AnalysisResult:
    risk_score = {
        "none": 0,
        "info": 15,
        "low": 35,
        "medium": 55,
        "high": 75,
        "critical": 95,
    }[severity]
    return AnalysisResult(
        data={
            "alert": alert,
            "severity": severity,
            "risk_score": risk_score,
            "summary": summary,
        },
        raw_text=f'{{"alert":{str(alert).lower()},"severity":"{severity}","summary":"{summary}"}}',
        model="fake-model",
        usage={"total_tokens": 10},
    )


def make_config() -> ServiceConfig:
    camera = CameraConfig(
        index=1,
        name="Dormitorio",
        rtsp_url="rtsp://camera-one/live",
        prompt="Detecta cambios relevantes.",
        poll_interval_seconds=1.0,
    )
    return ServiceConfig(
        poll_interval_seconds=1.0,
        reconnect_interval_seconds=1.0,
        frame_stale_after_seconds=60.0,
        max_api_calls_per_minute=0,
        max_frame_pixels=2_621_440,
        jpeg_quality=85,
        max_concurrent_analyses=1,
        rtsp_transport="tcp",
        rtsp_open_timeout_ms=1_000,
        rtsp_read_timeout_ms=1_000,
        save_captures=True,
        capture_dir=Path("unused"),
        capture_retention_days=7.0,
        capture_max_files_per_camera=1_000,
        events_jsonl_path=None,
        events_max_bytes=50_000_000,
        events_backup_count=5,
        log_level="INFO",
        cameras=(camera,),
        alibaba=AlibabaConfig(
            api_key="unused",
            base_url="https://example.test",
            model="unused",
            timeout_seconds=1.0,
            max_retries=0,
            max_completion_tokens=32,
        ),
        frame_width=8,
        frame_height=8,
    )


def make_snapshots(frames: list[np.ndarray]) -> list[FrameSnapshot]:
    captured_at = datetime.now(UTC)
    return [
        FrameSnapshot(frame=frame, captured_at=captured_at, sequence=index)
        for index, frame in enumerate(frames, start=1)
    ]


def build_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    frames: list[np.ndarray],
    outcomes: list[AnalysisResult | Exception],
) -> tuple[
    MonitoringService,
    FakeAnalyzer,
    MemoryEventSink,
    MemoryCaptureStore,
    InlineExecutor,
]:
    executors: list[InlineExecutor] = []

    def executor_factory(*args: Any, **kwargs: Any) -> InlineExecutor:
        executor = InlineExecutor(*args, **kwargs)
        executors.append(executor)
        return executor

    monkeypatch.setattr(service_module, "ThreadPoolExecutor", executor_factory)
    analyzer = FakeAnalyzer(outcomes)
    events = MemoryEventSink()
    captures = MemoryCaptureStore()
    service = MonitoringService(
        make_config(),
        analyzer,
        readers=[SequenceReader(make_snapshots(frames))],
        event_sink=events,
        capture_store=captures,
    )
    return service, analyzer, events, captures, executors[0]


def test_first_fresh_frame_is_analyzed_on_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = np.zeros((8, 8, 3), dtype=np.uint8)
    service, analyzer, events, captures, executor = build_service(
        monkeypatch,
        frames=[first],
        outcomes=[make_result("primer análisis", severity="critical")],
    )

    service.poll_once()

    assert executor.submissions == 1
    assert len(analyzer.calls) == 1
    assert analyzer.calls[0]["jpeg"].startswith(b"\xff\xd8")
    assert len(captures.calls) == 1
    assert captures.calls[0]["sequence"] == 1
    assert len(events.events) == 1
    event = events.events[0]
    assert event["event_type"] == "analysis.completed"
    assert len(event["event_id"]) == 32
    assert event["preview_path"].endswith(f"preview-{event['event_id']}.jpg")
    assert event["preview_available"] is True
    assert event["trigger"] == "poll"
    assert "variation_index_percent" not in event
    assert event["resolution"] == {"width": 8, "height": 8}
    assert service._states[0].last_seen_sequence == 1


def test_close_releases_resources_even_when_service_was_never_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, analyzer, _, _, executor = build_service(
        monkeypatch,
        frames=[],
        outcomes=[],
    )
    reader = service._states[0].reader

    service.close()
    service.close()

    assert reader.stopped is True
    assert analyzer.closed is True
    assert executor.shutdown_calls == [{"wait": True, "cancel_futures": True}]


def test_alibaba_executor_is_globally_serial_even_with_legacy_higher_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executors: list[InlineExecutor] = []
    monkeypatch.setattr(
        service_module,
        "ThreadPoolExecutor",
        lambda *args, **kwargs: executors.append(InlineExecutor(*args, **kwargs))
        or executors[-1],
    )
    service = MonitoringService(
        replace(make_config(), max_concurrent_analyses=99),
        FakeAnalyzer([]),
        readers=[SequenceReader([])],
        event_sink=MemoryEventSink(),
        capture_store=MemoryCaptureStore(),
    )

    assert executors[0].kwargs["max_workers"] == 1
    service.close()


def test_successful_analysis_saves_matching_operational_previews(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = np.zeros((8, 8, 3), dtype=np.uint8)
    changed = np.full((8, 8, 3), 255, dtype=np.uint8)
    service, analyzer, events, captures, executor = build_service(
        monkeypatch,
        frames=[first, changed],
        outcomes=[
            make_result("baseline", severity="low"),
            make_result("cambio", severity="low"),
        ],
    )

    service.poll_once()
    service.poll_once()

    # Operational previews are written before each semantic request and get
    # exactly the same JPEG bytes handed to the analyzer.
    assert len(captures.latest_calls) == 2
    assert len(captures.preview_calls) == 2
    assert [call["camera_id"] for call in captures.latest_calls] == ["CAM1", "CAM1"]
    assert [call["jpeg"] for call in captures.latest_calls] == [
        call["jpeg"] for call in analyzer.calls
    ]


def test_each_fresh_poll_frame_is_analyzed_even_when_pixels_are_identical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unchanged = np.full((8, 8, 3), 40, dtype=np.uint8)
    service, analyzer, events, captures, executor = build_service(
        monkeypatch,
        frames=[unchanged, unchanged.copy()],
        outcomes=[
            make_result("primero", severity="critical"),
            make_result("segundo", severity="critical"),
        ],
    )

    service.poll_once()
    service.poll_once()

    assert executor.submissions == 2
    assert len(analyzer.calls) == 2
    assert len(captures.calls) == 2
    assert [event["trigger"] for event in events.events] == ["poll", "poll"]


def test_same_rtsp_sequence_is_not_analyzed_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executors: list[InlineExecutor] = []
    monkeypatch.setattr(
        service_module,
        "ThreadPoolExecutor",
        lambda *args, **kwargs: executors.append(InlineExecutor()) or executors[-1],
    )
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    snapshot = FrameSnapshot(
        frame=frame,
        captured_at=datetime.now(UTC),
        sequence=7,
    )
    analyzer = FakeAnalyzer([make_result("único")])
    service = MonitoringService(
        make_config(),
        analyzer,
        readers=[SequenceReader([snapshot, snapshot])],
        event_sink=MemoryEventSink(),
        capture_store=MemoryCaptureStore(),
    )

    service.poll_once()
    service.poll_once()

    assert len(analyzer.calls) == 1
    assert executors[0].submissions == 1


def test_changed_frame_is_analyzed_without_a_delta_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = np.zeros((8, 8, 3), dtype=np.uint8)
    changed = np.full((8, 8, 3), 255, dtype=np.uint8)
    service, analyzer, events, captures, executor = build_service(
        monkeypatch,
        frames=[first, changed],
        outcomes=[
            make_result("baseline", severity="critical"),
            make_result("cambio", severity="critical"),
        ],
    )

    service.poll_once()
    service.poll_once()

    assert executor.submissions == 2
    assert len(captures.calls) == 2
    assert [event["trigger"] for event in events.events] == ["poll", "poll"]
    assert "change_threshold_percent" not in events.events[1]
    assert service._states[0].last_seen_sequence == 2


def test_failed_analysis_does_not_block_the_next_fresh_poll_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = np.zeros((8, 8, 3), dtype=np.uint8)
    changed = np.full((8, 8, 3), 255, dtype=np.uint8)
    service, analyzer, events, captures, executor = build_service(
        monkeypatch,
        frames=[baseline, changed, changed.copy()],
        outcomes=[
            make_result("baseline", severity="critical"),
            RuntimeError("semantic API unavailable"),
            make_result("retry succeeded", severity="critical"),
        ],
    )

    service.poll_once()
    service.poll_once()
    service.poll_once()

    assert executor.submissions == 3
    assert len(analyzer.calls) == 3
    # Only the two successful analyses can produce a capture; the failed
    # attempt never reaches the severity check, so it never saves a JPEG.
    assert len(captures.calls) == 2
    assert [call["sequence"] for call in captures.calls] == [1, 3]
    assert [event["event_type"] for event in events.events] == [
        "analysis.completed",
        "analysis.failed",
        "analysis.completed",
    ]
    assert [event["trigger"] for event in events.events] == [
        "poll",
        "poll",
        "poll",
    ]
    assert events.events[1]["error"] == "RuntimeError"
    assert events.events[1]["snapshot_path"] is None
    assert service._states[0].last_seen_sequence == 3


def test_keeps_newest_candidate_while_analysis_is_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manual = ManualExecutor()
    monkeypatch.setattr(
        service_module,
        "ThreadPoolExecutor",
        lambda *args, **kwargs: manual,
    )
    baseline = np.zeros((8, 8, 3), dtype=np.uint8)
    incident = np.full((8, 8, 3), 255, dtype=np.uint8)
    later = np.full((8, 8, 3), 80, dtype=np.uint8)
    analyzer = FakeAnalyzer(
        [
            make_result("baseline", severity="critical"),
            make_result("incident", severity="critical"),
        ]
    )
    events = MemoryEventSink()
    captures = MemoryCaptureStore()
    service = MonitoringService(
        make_config(),
        analyzer,
        readers=[SequenceReader(make_snapshots([baseline, incident, later]))],
        event_sink=events,
        capture_store=captures,
    )

    service.poll_once()
    service.poll_once()
    service.poll_once()

    assert len(manual.jobs) == 1
    # The capture-store save now happens once the analysis result is known
    # (severity gating), not at scheduling time, so nothing is captured yet
    # while the first job is still in flight.
    assert len(captures.calls) == 0
    assert service._states[0].pending is not None
    assert service._states[0].pending.snapshot.sequence == 3

    manual.complete_next()

    assert len(manual.jobs) == 1
    assert [call["sequence"] for call in captures.calls] == [1]
    manual.complete_next()
    assert [call["sequence"] for call in captures.calls] == [1, 3]
    assert [event["trigger"] for event in events.events] == ["poll", "poll"]


def test_alibaba_has_one_active_job_and_keeps_other_camera_replaceable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manual = ManualExecutor()
    monkeypatch.setattr(
        service_module,
        "ThreadPoolExecutor",
        lambda *args, **kwargs: manual,
    )
    first_camera = make_config().cameras[0]
    second_camera = replace(
        first_camera,
        index=2,
        name="Living",
        rtsp_url="rtsp://camera-two/live",
    )
    service = MonitoringService(
        replace(make_config(), cameras=(first_camera, second_camera)),
        FakeAnalyzer([make_result("CAM1"), make_result("CAM2")]),
        readers=[
            SequenceReader(make_snapshots([np.zeros((8, 8, 3), dtype=np.uint8)])),
            SequenceReader(make_snapshots([np.full((8, 8, 3), 255, dtype=np.uint8)])),
        ],
        event_sink=MemoryEventSink(),
        capture_store=MemoryCaptureStore(),
    )

    service.poll_once()

    assert len(manual.jobs) == 1
    assert service._states[0].in_flight is True
    assert service._states[1].in_flight is False
    assert service._states[1].pending is not None

    manual.complete_next()

    assert len(manual.jobs) == 1
    assert service._states[1].in_flight is True
    assert service._states[1].pending is None
    manual.complete_next()
    assert service._analysis_in_flight is False


def test_below_threshold_analysis_is_recorded_without_saving_an_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    service, analyzer, events, captures, executor = build_service(
        monkeypatch,
        frames=[frame],
        outcomes=[make_result("nada relevante", severity="low")],
    )

    service.poll_once()

    assert len(analyzer.calls) == 1
    assert captures.calls == []
    assert len(events.events) == 1
    event = events.events[0]
    assert event["event_type"] == "analysis.completed"
    assert event["snapshot_path"] is None


@pytest.mark.parametrize("severity", ["high", "critical"])
def test_at_or_above_threshold_analysis_saves_an_image(
    monkeypatch: pytest.MonkeyPatch,
    severity: str,
) -> None:
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    service, analyzer, events, captures, executor = build_service(
        monkeypatch,
        frames=[frame],
        outcomes=[make_result("evento relevante", severity=severity)],
    )

    service.poll_once()

    assert len(captures.calls) == 1
    assert captures.calls[0]["sequence"] == 1
    event = events.events[0]
    assert event["event_type"] == "analysis.completed"
    assert event["snapshot_path"] is not None
    assert event["snapshot_path"] == f"memory://{captures.calls[0]['camera_id']}/1.jpg"


def test_failed_analysis_snapshot_path_is_always_none_regardless_of_severity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    service, analyzer, events, captures, executor = build_service(
        monkeypatch,
        frames=[frame],
        outcomes=[RuntimeError("semantic API unavailable")],
    )

    service.poll_once()

    assert captures.calls == []
    assert len(events.events) == 1
    event = events.events[0]
    assert event["event_type"] == "analysis.failed"
    assert event["snapshot_path"] is None
    assert event["preview_path"] is None
    assert event["preview_available"] is True
    assert len(captures.latest_calls) == 1
    assert captures.latest_calls[0]["jpeg"] == analyzer.calls[0]["jpeg"]
    assert captures.latest_calls[0]["camera_id"] == "CAM1"
    assert captures.preview_calls == []


def test_changing_save_image_min_severity_moves_the_capture_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executors: list[InlineExecutor] = []

    def executor_factory(*args: Any, **kwargs: Any) -> InlineExecutor:
        executor = InlineExecutor(*args, **kwargs)
        executors.append(executor)
        return executor

    monkeypatch.setattr(service_module, "ThreadPoolExecutor", executor_factory)
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    analyzer = FakeAnalyzer([make_result("alerta alta", severity="high")])
    captures = MemoryCaptureStore()
    config = replace(make_config(), save_image_min_severity="critical")
    service = MonitoringService(
        config,
        analyzer,
        readers=[SequenceReader(make_snapshots([frame]))],
        event_sink=MemoryEventSink(),
        capture_store=captures,
    )

    service.poll_once()

    # Under the default threshold ("high") this result would have saved an
    # image; raising the bar to "critical" means a "high" result no longer
    # qualifies.
    assert captures.calls == []


def test_event_sink_failure_does_not_block_later_poll_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingEventSink:
        def publish(self, event: dict[str, Any]) -> None:
            raise OSError("disk full")

    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    executors: list[InlineExecutor] = []

    def executor_factory(*args: Any, **kwargs: Any) -> InlineExecutor:
        executor = InlineExecutor(*args, **kwargs)
        executors.append(executor)
        return executor

    monkeypatch.setattr(service_module, "ThreadPoolExecutor", executor_factory)
    analyzer = FakeAnalyzer([make_result("first"), make_result("retry")])
    service = MonitoringService(
        make_config(),
        analyzer,
        readers=[SequenceReader(make_snapshots([frame, frame.copy()]))],
        event_sink=FailingEventSink(),
        capture_store=MemoryCaptureStore(),
    )

    service.poll_once()
    service.poll_once()

    assert len(analyzer.calls) == 2
    assert service._states[0].last_seen_sequence == 2


def test_stale_pending_frame_is_discarded_before_api_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executors: list[InlineExecutor] = []
    monkeypatch.setattr(
        service_module,
        "ThreadPoolExecutor",
        lambda *args, **kwargs: executors.append(InlineExecutor()) or executors[-1],
    )
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    stale_snapshot = FrameSnapshot(
        frame=frame,
        captured_at=datetime.now(UTC) - timedelta(seconds=61),
        sequence=1,
    )
    analyzer = FakeAnalyzer([])
    service = MonitoringService(
        make_config(),
        analyzer,
        readers=[SequenceReader([])],
        event_sink=MemoryEventSink(),
        capture_store=MemoryCaptureStore(),
    )
    state = service._states[0]
    state.pending = service_module._PendingCandidate(snapshot=stale_snapshot, frame=frame)

    service._try_schedule_pending(state)

    assert state.pending is None
    assert analyzer.calls == []
    assert executors[0].submissions == 0


def test_sliding_window_rate_limiter_enforces_and_releases_global_budget() -> None:
    limiter = _SlidingWindowRateLimiter(2)

    assert limiter.try_acquire(0.0)
    assert limiter.try_acquire(1.0)
    assert not limiter.try_acquire(59.9)
    assert limiter.try_acquire(60.0)


def test_advance_schedule_moves_forward_by_interval_when_not_behind() -> None:
    assert _advance_schedule(10.0, 12.0, 5.0) == 15.0


def test_advance_schedule_catches_up_from_now_when_still_behind() -> None:
    # current + interval (15.0) would still be <= now (20.0): a real clock
    # tick was missed (e.g. the process was blocked), so the next tick is
    # rebased on "now" instead of scheduling a backlog of overdue polls.
    assert _advance_schedule(10.0, 20.0, 5.0) == 25.0


def test_advance_schedule_catches_up_on_the_exact_boundary() -> None:
    # current + interval lands exactly on "now": still due immediately, so
    # this must also clamp forward rather than schedule a tick for "now"
    # itself (which run()'s loop would treat as due again on the next pass).
    assert _advance_schedule(10.0, 15.0, 5.0) == 20.0


def test_run_honors_each_camera_poll_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This drives the real MonitoringService.run() loop in a background
    # thread using the real wall clock (no monkeypatched time.monotonic):
    # synchronizing a fake monotonic clock with run()'s real, blocking
    # self._stop_event.wait() turned out to be the fragile option (the wait
    # call has no idea the clock is fake, so it would really sleep for
    # whatever duration the mocked arithmetic produced). Using tiny real
    # intervals with a wide gap between the "fast" and "slow" camera keeps
    # this deterministic without needing clock mocking.
    executors: list[InlineExecutor] = []
    monkeypatch.setattr(
        service_module,
        "ThreadPoolExecutor",
        lambda *args, **kwargs: executors.append(InlineExecutor()) or executors[-1],
    )
    base_camera = CameraConfig(
        index=1,
        name="Rápida",
        rtsp_url="rtsp://camera-fast/live",
        prompt="Detecta cambios relevantes.",
        poll_interval_seconds=0.02,
    )
    slow_camera = replace(
        base_camera,
        index=2,
        name="Lenta",
        rtsp_url="rtsp://camera-slow/live",
        poll_interval_seconds=0.06,
    )
    config = replace(
        make_config(),
        cameras=(base_camera, slow_camera),
        poll_interval_seconds=9.0,
    )
    analyzer = FakeAnalyzer([])
    service = MonitoringService(
        config,
        analyzer,
        readers=[SequenceReader([]), SequenceReader([])],
        event_sink=MemoryEventSink(),
        capture_store=MemoryCaptureStore(),
    )

    poll_counts: dict[str, int] = {}
    original_poll_camera = service._poll_camera

    def counting_poll_camera(state: Any) -> None:
        poll_counts[state.camera.identifier] = poll_counts.get(state.camera.identifier, 0) + 1
        original_poll_camera(state)

    monkeypatch.setattr(service, "_poll_camera", counting_poll_camera)

    thread = threading.Thread(target=service.run, daemon=True)
    thread.start()
    try:
        time.sleep(0.3)
    finally:
        service.request_stop()
        thread.join(timeout=2.0)

    assert not thread.is_alive()
    # Each camera uses its own cadence; the faster one must run materially
    # more often even though ServiceConfig retains a legacy/default value.
    assert poll_counts.get("CAM1", 0) >= 8
    assert poll_counts.get("CAM2", 0) >= 3
    assert poll_counts["CAM1"] > poll_counts["CAM2"]


def test_start_staggers_first_poll_across_the_shortest_camera_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service_module.time, "monotonic", lambda: 100.0)
    first = replace(make_config().cameras[0], poll_interval_seconds=30.0)
    second = replace(
        first,
        index=2,
        name="Living",
        rtsp_url="rtsp://camera-two/live",
        poll_interval_seconds=60.0,
    )
    service = MonitoringService(
        replace(make_config(), cameras=(first, second)),
        FakeAnalyzer([]),
        readers=[SequenceReader([]), SequenceReader([])],
        event_sink=MemoryEventSink(),
        capture_store=MemoryCaptureStore(),
    )

    service.start()

    assert [state.next_poll_at for state in service._states] == [100.0, 115.0]
    service.close()


def test_run_retries_quickly_when_reader_has_no_frame_on_first_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service_module, "_INITIAL_FRAME_RETRY_SECONDS", 0.01)
    executors: list[InlineExecutor] = []
    monkeypatch.setattr(
        service_module,
        "ThreadPoolExecutor",
        lambda *args, **kwargs: executors.append(InlineExecutor(*args, **kwargs))
        or executors[-1],
    )
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    snapshot = FrameSnapshot(
        frame=frame,
        captured_at=datetime.now(UTC),
        sequence=1,
    )
    analyzer = FakeAnalyzer([make_result("primera captura")])
    service = MonitoringService(
        replace(
            make_config(),
            cameras=(
                replace(
                    make_config().cameras[0],
                    poll_interval_seconds=30.0,
                ),
            ),
        ),
        analyzer,
        readers=[SequenceReader([None, snapshot])],
        event_sink=MemoryEventSink(),
        capture_store=MemoryCaptureStore(),
    )

    thread = threading.Thread(target=service.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 0.5
    while not analyzer.calls and time.monotonic() < deadline:
        time.sleep(0.005)
    service.request_stop()
    thread.join(timeout=2.0)

    assert len(analyzer.calls) == 1
    assert not thread.is_alive()


def _variation_gate_config(**overrides: Any) -> ServiceConfig:
    return replace(
        make_config(),
        change_threshold_percent=10.0,
        delta_width=4,
        delta_height=4,
        pixel_change_threshold=24,
        **overrides,
    )


def _inline_executor_patch(monkeypatch: pytest.MonkeyPatch) -> list[InlineExecutor]:
    executors: list[InlineExecutor] = []
    monkeypatch.setattr(
        service_module,
        "ThreadPoolExecutor",
        lambda *args, **kwargs: executors.append(InlineExecutor()) or executors[-1],
    )
    return executors


def test_change_threshold_percent_zero_disables_gating(monkeypatch: pytest.MonkeyPatch) -> None:
    _inline_executor_patch(monkeypatch)
    calm = np.zeros((8, 8, 3), dtype=np.uint8)
    analyzer = FakeAnalyzer([make_result("a", severity="none"), make_result("b", severity="none")])
    service = MonitoringService(
        make_config(),  # change_threshold_percent defaults to 0.0 (feature off)
        analyzer,
        readers=[SequenceReader(make_snapshots([calm, calm]))],
        event_sink=MemoryEventSink(),
        capture_store=MemoryCaptureStore(),
    )

    service.poll_once()
    service.poll_once()

    assert len(analyzer.calls) == 2


def test_skips_analysis_when_variation_below_threshold_and_last_severity_is_calm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _inline_executor_patch(monkeypatch)
    calm = np.zeros((8, 8, 3), dtype=np.uint8)
    analyzer = FakeAnalyzer([make_result("calm", severity="none")])
    events = MemoryEventSink()
    captures = MemoryCaptureStore()
    service = MonitoringService(
        _variation_gate_config(),
        analyzer,
        readers=[SequenceReader(make_snapshots([calm, calm]))],
        event_sink=events,
        capture_store=captures,
    )

    service.poll_once()  # first frame ever: no baseline to compare against, always analyzed
    service.poll_once()  # identical frame, last severity calm -> skipped

    assert len(analyzer.calls) == 1
    assert len(captures.latest_calls) == 2  # operational preview keeps updating on skip
    assert [event["event_type"] for event in events.events] == [
        "analysis.completed",
        "analysis.skipped",
    ]
    skipped = events.events[1]
    assert skipped["variation_index_percent"] == pytest.approx(0.0)
    assert skipped["change_threshold_percent"] == pytest.approx(10.0)


def test_does_not_skip_when_last_severity_is_medium_or_above(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _inline_executor_patch(monkeypatch)
    calm = np.zeros((8, 8, 3), dtype=np.uint8)
    analyzer = FakeAnalyzer(
        [make_result("fall", severity="high"), make_result("still on the floor", severity="high")]
    )
    events = MemoryEventSink()
    service = MonitoringService(
        _variation_gate_config(),
        analyzer,
        readers=[SequenceReader(make_snapshots([calm, calm]))],
        event_sink=events,
        capture_store=MemoryCaptureStore(),
    )

    service.poll_once()
    service.poll_once()

    # A stationary emergency (identical frames, high severity) must never be
    # silently skipped just because pixel variation is low.
    assert len(analyzer.calls) == 2
    assert [event["event_type"] for event in events.events] == [
        "analysis.completed",
        "analysis.completed",
    ]


def test_reanalyzes_when_variation_exceeds_threshold_despite_calm_last_severity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _inline_executor_patch(monkeypatch)
    calm = np.zeros((8, 8, 3), dtype=np.uint8)
    changed = np.full((8, 8, 3), 255, dtype=np.uint8)
    analyzer = FakeAnalyzer(
        [make_result("calm", severity="none"), make_result("changed", severity="none")]
    )
    service = MonitoringService(
        _variation_gate_config(),
        analyzer,
        readers=[SequenceReader(make_snapshots([calm, changed]))],
        event_sink=MemoryEventSink(),
        capture_store=MemoryCaptureStore(),
    )

    service.poll_once()
    service.poll_once()

    assert len(analyzer.calls) == 2


def test_notifies_telegram_when_severity_meets_camera_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _inline_executor_patch(monkeypatch)
    camera = replace(make_config().cameras[0], notification_threshold="high")
    config = replace(make_config(), cameras=(camera,))
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    analyzer = FakeAnalyzer([make_result("posible caída", severity="high")])
    notifier = FakeNotifier()
    service = MonitoringService(
        config,
        analyzer,
        readers=[SequenceReader(make_snapshots([frame]))],
        event_sink=MemoryEventSink(),
        capture_store=MemoryCaptureStore(),
        notifier=notifier,
    )

    service.poll_once()

    assert len(notifier.calls) == 1
    assert "posible caída" in notifier.calls[0]["caption"]
    assert camera.name in notifier.calls[0]["caption"]


def test_does_not_notify_below_camera_notification_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _inline_executor_patch(monkeypatch)
    camera = replace(make_config().cameras[0], notification_threshold="high")
    config = replace(make_config(), cameras=(camera,))
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    analyzer = FakeAnalyzer([make_result("nada relevante", severity="low")])
    notifier = FakeNotifier()
    service = MonitoringService(
        config,
        analyzer,
        readers=[SequenceReader(make_snapshots([frame]))],
        event_sink=MemoryEventSink(),
        capture_store=MemoryCaptureStore(),
        notifier=notifier,
    )

    service.poll_once()

    assert notifier.calls == []


def test_no_notifier_configured_never_calls_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    _inline_executor_patch(monkeypatch)
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    analyzer = FakeAnalyzer([make_result("posible caída", severity="critical")])
    service = MonitoringService(
        make_config(),  # no telegram_bot_token/telegram_chat_id -> notifier is None
        analyzer,
        readers=[SequenceReader(make_snapshots([frame]))],
        event_sink=MemoryEventSink(),
        capture_store=MemoryCaptureStore(),
    )

    service.poll_once()  # must not raise even though no notifier is configured

    assert len(analyzer.calls) == 1


def test_telegram_enabled_false_disables_sending_even_with_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _inline_executor_patch(monkeypatch)
    config = replace(
        make_config(),
        telegram_enabled=False,
        telegram_bot_token="fake-token",
        telegram_chat_id="fake-chat",
    )
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    analyzer = FakeAnalyzer([make_result("posible caída", severity="critical")])
    service = MonitoringService(
        config,
        analyzer,
        readers=[SequenceReader(make_snapshots([frame]))],
        event_sink=MemoryEventSink(),
        capture_store=MemoryCaptureStore(),
    )

    assert service._notifier is None

    service.poll_once()  # must not attempt any real network call

    assert len(analyzer.calls) == 1
