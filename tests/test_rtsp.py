from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

import numpy as np
import pytest

import iris.rtsp as rtsp_module
from iris.models import CameraConfig, Frame
from iris.rtsp import LatestFrameReader


class FakeCapture:
    def __init__(
        self,
        *,
        opened: bool = True,
        reads: list[tuple[bool, Frame | None]] | None = None,
        hold_when_exhausted: bool = False,
    ) -> None:
        self.opened = opened
        self.reads = deque(reads or [])
        self.hold_when_exhausted = hold_when_exhausted
        self.read_calls = 0
        self.release_calls = 0
        self.waiting = threading.Event()
        self.released = threading.Event()
        self._reader_stop_event: threading.Event | None = None

    def bind_reader_stop(self, stop_event: threading.Event) -> None:
        self._reader_stop_event = stop_event

    def isOpened(self) -> bool:
        return self.opened

    def read(self) -> tuple[bool, Frame | None]:
        if not self.opened:
            raise AssertionError("read() must not be called on a closed capture")
        self.read_calls += 1
        if self.reads:
            return self.reads.popleft()
        if not self.hold_when_exhausted:
            return False, None

        if self._reader_stop_event is None:
            raise AssertionError("the fake capture was not bound to the reader")
        self.waiting.set()
        while not self._reader_stop_event.wait(0.005):
            pass
        return False, None

    def release(self) -> None:
        self.release_calls += 1
        self.released.set()


class FakeCaptureFactory:
    def __init__(self, captures: list[FakeCapture]) -> None:
        self._captures = deque(captures)
        self.calls: list[tuple[str, int, int]] = []

    def __call__(
        self,
        url: str,
        open_timeout_ms: int,
        read_timeout_ms: int,
    ) -> FakeCapture:
        self.calls.append((url, open_timeout_ms, read_timeout_ms))
        if not self._captures:
            raise AssertionError("LatestFrameReader opened an unexpected extra capture")
        return self._captures.popleft()


def make_camera() -> CameraConfig:
    return CameraConfig(
        index=2,
        name="Pasillo",
        rtsp_url="rtsp://camera-two/live",
        prompt="Detecta incidentes.",
    )


def make_reader(
    captures: list[FakeCapture],
) -> tuple[LatestFrameReader, FakeCaptureFactory]:
    factory = FakeCaptureFactory(captures)
    reader = LatestFrameReader(
        make_camera(),
        reconnect_interval_seconds=0.001,
        open_timeout_ms=321,
        read_timeout_ms=654,
        rtsp_transport="tcp",
        capture_factory=factory,
    )
    for capture in captures:
        capture.bind_reader_stop(reader._stop_event)
    return reader, factory


def wait_until(predicate: Callable[[], bool], *, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.001)
    assert predicate(), "condition was not met before the bounded timeout"


def latest_sequence(reader: LatestFrameReader) -> int | None:
    snapshot = reader.latest()
    return None if snapshot is None else snapshot.sequence


def test_latest_retains_only_newest_frame_and_returns_defensive_copies() -> None:
    first = np.zeros((3, 4, 3), dtype=np.uint8)
    newest = np.full((3, 4, 3), 173, dtype=np.uint8)
    capture = FakeCapture(
        reads=[(True, first), (True, newest)],
        hold_when_exhausted=True,
    )
    reader, _ = make_reader([capture])

    assert reader.latest() is None
    reader.start()
    try:
        wait_until(lambda: latest_sequence(reader) == 2)

        snapshot = reader.latest()
        assert snapshot is not None
        assert snapshot.sequence == 2
        np.testing.assert_array_equal(snapshot.frame, newest)

        snapshot.frame.fill(0)
        fresh_snapshot = reader.latest()
        assert fresh_snapshot is not None
        assert fresh_snapshot.frame is not snapshot.frame
        np.testing.assert_array_equal(fresh_snapshot.frame, newest)
    finally:
        reader.stop()

    assert capture.release_calls == 1


def test_reconnects_after_read_failure_and_releases_each_capture() -> None:
    first = np.full((2, 2, 3), 10, dtype=np.uint8)
    after_reconnect = np.full((2, 2, 3), 240, dtype=np.uint8)
    failed_capture = FakeCapture(reads=[(True, first), (False, None)])
    replacement_capture = FakeCapture(
        reads=[(True, after_reconnect)],
        hold_when_exhausted=True,
    )
    reader, factory = make_reader([failed_capture, replacement_capture])

    reader.start()
    try:
        wait_until(lambda: latest_sequence(reader) == 2)
        assert factory.calls == [
            ("rtsp://camera-two/live", 321, 654),
            ("rtsp://camera-two/live", 321, 654),
        ]
        assert failed_capture.release_calls == 1
        snapshot = reader.latest()
        assert snapshot is not None
        np.testing.assert_array_equal(snapshot.frame, after_reconnect)
    finally:
        reader.stop()

    assert replacement_capture.release_calls == 1


def test_reconnects_after_open_failure_without_reading_closed_capture() -> None:
    closed_capture = FakeCapture(opened=False)
    frame = np.full((2, 3, 3), 91, dtype=np.uint8)
    replacement_capture = FakeCapture(
        reads=[(True, frame)],
        hold_when_exhausted=True,
    )
    reader, factory = make_reader([closed_capture, replacement_capture])

    reader.start()
    try:
        wait_until(lambda: latest_sequence(reader) == 1)
        assert len(factory.calls) == 2
        assert closed_capture.read_calls == 0
        assert closed_capture.release_calls == 1
    finally:
        reader.stop()

    assert replacement_capture.release_calls == 1


def test_stop_joins_reader_and_releases_active_capture() -> None:
    capture = FakeCapture(hold_when_exhausted=True)
    reader, factory = make_reader([capture])
    reader.start()
    assert capture.waiting.wait(1.0)

    assert reader.stop()

    assert reader._thread is not None
    assert not reader._thread.is_alive()
    assert capture.release_calls == 1
    assert len(factory.calls) == 1

    assert reader.stop()
    assert capture.release_calls == 1


def test_request_stop_signals_reader_before_bounded_join() -> None:
    capture = FakeCapture(hold_when_exhausted=True)
    reader, _ = make_reader([capture])
    reader.start()
    assert capture.waiting.wait(1.0)

    reader.request_stop()
    wait_until(lambda: reader._thread is not None and not reader._thread.is_alive())

    assert capture.release_calls == 1
    assert reader.stop()
    assert capture.release_calls == 1


def test_status_callback_reports_connectivity_transitions() -> None:
    first = FakeCapture(reads=[(False, None)])
    second = FakeCapture(
        reads=[(True, np.zeros((2, 2, 3), dtype=np.uint8))],
        hold_when_exhausted=True,
    )
    factory = FakeCaptureFactory([first, second])
    events: list[dict[str, object]] = []
    reader = LatestFrameReader(
        make_camera(),
        reconnect_interval_seconds=0.001,
        open_timeout_ms=321,
        read_timeout_ms=654,
        rtsp_transport="tcp",
        capture_factory=factory,
        status_callback=events.append,
    )
    for capture in (first, second):
        capture.bind_reader_stop(reader._stop_event)

    reader.start()
    try:
        wait_until(lambda: latest_sequence(reader) == 1)
    finally:
        assert reader.stop()

    assert [event["event_type"] for event in events] == [
        "camera.connected",
        "camera.offline",
        "camera.connected",
    ]
    assert all(event["camera_id"] == "CAM2" for event in events)


def test_connected_reader_emits_bounded_heartbeats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rtsp_module, "_STATUS_HEARTBEAT_SECONDS", 0.0)
    capture = FakeCapture(
        reads=[
            (True, np.zeros((2, 2, 3), dtype=np.uint8)),
            (True, np.ones((2, 2, 3), dtype=np.uint8)),
        ],
        hold_when_exhausted=True,
    )
    events: list[dict[str, object]] = []
    reader = LatestFrameReader(
        make_camera(),
        reconnect_interval_seconds=0.001,
        open_timeout_ms=321,
        read_timeout_ms=654,
        rtsp_transport="tcp",
        capture_factory=FakeCaptureFactory([capture]),
        status_callback=events.append,
    )
    capture.bind_reader_stop(reader._stop_event)

    reader.start()
    try:
        wait_until(lambda: latest_sequence(reader) == 2)
    finally:
        assert reader.stop()

    assert events[0]["reason"] == "connected"
    assert [event["reason"] for event in events[1:]] == ["heartbeat", "heartbeat"]


def test_open_capture_passes_timeouts_as_params_and_sets_buffer_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OpenedCapture:
        def __init__(self) -> None:
            self.set_calls: list[tuple[int, int]] = []

        def isOpened(self) -> bool:
            return True

        def set(self, property_id: int, value: int) -> bool:
            self.set_calls.append((property_id, value))
            return True

    capture = OpenedCapture()
    video_capture_calls: list[tuple[str, int, list[int]]] = []

    def video_capture(url: str, backend: int, params: list[int]) -> OpenedCapture:
        video_capture_calls.append((url, backend, params))
        return capture

    monkeypatch.setattr(rtsp_module.cv2, "CAP_FFMPEG", 1_900)
    monkeypatch.setattr(rtsp_module.cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", 101)
    monkeypatch.setattr(rtsp_module.cv2, "CAP_PROP_READ_TIMEOUT_MSEC", 102)
    monkeypatch.setattr(rtsp_module.cv2, "CAP_PROP_BUFFERSIZE", 103)
    monkeypatch.setattr(rtsp_module.cv2, "VideoCapture", video_capture)

    result = rtsp_module._open_capture("rtsp://example/live", 2_500, 3_500)

    assert result is capture
    assert video_capture_calls == [("rtsp://example/live", 1_900, [101, 2_500, 102, 3_500])]
    assert capture.set_calls == [(103, 1)]
