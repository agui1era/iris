from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from iris.sinks import CaptureStore, EventSink, MongoEventSink, MultiEventSink


def test_event_sink_persists_full_event_securely_but_logs_only_metadata(
    tmp_path: Path,
    caplog,
) -> None:
    path = tmp_path / "private" / "events.jsonl"
    sink = EventSink(path)
    event = {
        "event_type": "analysis.completed",
        "camera_id": "CAM1",
        "captured_at": "2026-07-27T12:00:00+00:00",
        "analysis": {
            "risk_score": 75,
            "alert": True,
            "severity": "high",
            "event": "possible_fall",
            "summary": "Sensitive observation that must stay out of INFO logs.",
        },
    }

    with caplog.at_level(logging.INFO, logger="iris.events"):
        sink.publish(event)

    assert json.loads(path.read_text(encoding="utf-8")) == event
    assert path.stat().st_mode & 0o077 == 0
    assert path.parent.stat().st_mode & 0o077 == 0
    assert "Sensitive observation" not in caplog.text
    assert "possible_fall" in caplog.text


def test_capture_store_uses_private_directory_and_file_permissions(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "captures"
    store = CaptureStore(directory, enabled=True)

    saved = store.save(
        b"jpeg-data",
        camera_id="CAM3",
        camera_name="Living principal",
        captured_at_compact="20260727T120000.000000Z",
        sequence=7,
    )

    assert saved is not None
    path = Path(saved)
    assert path.read_bytes() == b"jpeg-data"
    assert path.stat().st_mode & 0o077 == 0
    assert path.parent.stat().st_mode & 0o077 == 0


def test_capture_store_can_be_disabled_without_creating_directory(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "captures"
    store = CaptureStore(directory, enabled=False)

    saved = store.save(
        b"jpeg-data",
        camera_id="CAM1",
        camera_name="Dormitorio",
        captured_at_compact="20260727T120000.000000Z",
        sequence=1,
    )

    assert saved is None
    assert not directory.exists()


def test_event_sink_rotates_jsonl_before_it_exceeds_limit(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    sink = EventSink(path, max_bytes=100, backup_count=2)

    sink.publish({"event_type": "first", "camera_id": "CAM1", "payload": "x" * 60})
    sink.publish({"event_type": "second", "camera_id": "CAM1", "payload": "y" * 60})

    assert json.loads(path.read_text(encoding="utf-8"))["event_type"] == "second"
    assert (
        json.loads(path.with_name("events.jsonl.1").read_text(encoding="utf-8"))["event_type"]
        == "first"
    )


def test_capture_store_prunes_oldest_files_above_per_camera_limit(
    tmp_path: Path,
) -> None:
    store = CaptureStore(
        tmp_path / "captures",
        enabled=True,
        max_files_per_camera=2,
    )
    saved_paths: list[Path] = []
    for sequence in range(1, 4):
        saved = store.save(
            b"jpeg",
            camera_id="CAM1",
            camera_name="Dormitorio",
            captured_at_compact=f"20260727T12000{sequence}.000000Z",
            sequence=sequence,
        )
        assert saved is not None
        path = Path(saved)
        saved_paths.append(path)
        os.utime(path, (sequence, sequence))

    assert not saved_paths[0].exists()
    assert saved_paths[1].exists()
    assert saved_paths[2].exists()


def test_save_latest_writes_to_fixed_path_with_secure_permissions(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "captures"
    # save_latest must work even when historical capture saving is disabled:
    # it's an operational preview, not the evidence-retention mechanism.
    store = CaptureStore(directory, enabled=False)

    assert store.save_latest(b"jpeg-bytes", camera_id="CAM1")

    path = directory / "CAM1" / "latest.jpg"
    assert path.read_bytes() == b"jpeg-bytes"
    assert path.stat().st_mode & 0o077 == 0
    assert path.parent.stat().st_mode & 0o077 == 0


def test_save_latest_overwrites_rather_than_accumulating(tmp_path: Path) -> None:
    directory = tmp_path / "captures"
    store = CaptureStore(directory, enabled=True)

    store.save_latest(b"first-frame", camera_id="CAM1")
    store.save_latest(b"second-frame", camera_id="CAM1")

    camera_dir = directory / "CAM1"
    jpeg_files = list(camera_dir.glob("*.jpg"))
    assert len(jpeg_files) == 1
    assert jpeg_files[0].name == "latest.jpg"
    assert jpeg_files[0].read_bytes() == b"second-frame"


def test_save_preview_creates_immutable_event_paired_file(tmp_path: Path) -> None:
    directory = tmp_path / "captures"
    store = CaptureStore(directory, enabled=False)
    event_id = "832e8c5a7f6c4bf9b1066a387928fa28"

    saved = store.save_preview(
        b"event-frame",
        camera_id="CAM1",
        event_id=event_id,
    )

    assert saved is not None
    path = Path(saved)
    assert path.name == f"preview-{event_id}.jpg"
    assert path.read_bytes() == b"event-frame"
    assert path.stat().st_mode & 0o077 == 0
    assert not list(path.parent.glob("*.tmp"))


def test_save_preview_rejects_unsafe_event_id(tmp_path: Path) -> None:
    directory = tmp_path / "captures"
    store = CaptureStore(directory, enabled=False)

    saved = store.save_preview(
        b"event-frame",
        camera_id="CAM1",
        event_id="../../escape",
    )

    assert saved is None
    assert not directory.exists()


def test_save_latest_never_raises_and_logs_a_warning_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog,
) -> None:
    directory = tmp_path / "captures"
    store = CaptureStore(directory, enabled=True)

    def _raise(*args: Any, **kwargs: Any) -> int:
        raise OSError("disk full")

    monkeypatch.setattr("iris.sinks.os.open", _raise)

    with caplog.at_level(logging.WARNING, logger="iris.events"):
        result = store.save_latest(b"jpeg-bytes", camera_id="CAM1")

    assert result is False
    assert not (directory / "CAM1" / "latest.jpg").exists()
    assert "CAM1" in caplog.text


class _FakeCollection:
    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []

    def insert_one(self, document: dict[str, Any]) -> None:
        self.documents.append(document)


def test_mongo_event_sink_construction_and_close_do_not_connect() -> None:
    sink = MongoEventSink("mongodb://localhost:1/db", "iris", "events")

    sink.close()


def test_mongo_event_sink_persists_full_event_securely_but_logs_only_metadata(
    caplog,
) -> None:
    sink = MongoEventSink("mongodb://localhost:1/db", "iris", "events")
    fake_collection = _FakeCollection()
    sink._collection = fake_collection
    event = {
        "event_type": "analysis.completed",
        "camera_id": "CAM1",
        "captured_at": "2026-07-27T12:00:00+00:00",
        "analysis": {
            "risk_score": 75,
            "alert": True,
            "severity": "high",
            "event": "possible_fall",
            "summary": "Sensitive observation that must stay out of INFO logs.",
        },
    }

    with caplog.at_level(logging.INFO, logger="iris.events"):
        sink.publish(event)

    assert len(fake_collection.documents) == 1
    document = fake_collection.documents[0]
    for key, value in event.items():
        assert document[key] == value
    assert "received_at" in document
    datetime.fromisoformat(document["received_at"])
    assert "Sensitive observation" not in caplog.text
    assert "possible_fall" in caplog.text

    sink.close()


def test_mongo_event_sink_does_not_overwrite_existing_received_at() -> None:
    sink = MongoEventSink("mongodb://localhost:1/db", "iris", "events")
    fake_collection = _FakeCollection()
    sink._collection = fake_collection
    event = {
        "event_type": "analysis.completed",
        "camera_id": "CAM1",
        "received_at": "2020-01-01T00:00:00+00:00",
    }

    sink.publish(event)

    assert fake_collection.documents[0]["received_at"] == "2020-01-01T00:00:00+00:00"


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.closed = False

    def publish(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def close(self) -> None:
        self.closed = True


class FailingSink:
    def publish(self, event: dict[str, Any]) -> None:
        raise RuntimeError("boom")


def test_multi_event_sink_fans_out_to_all_sinks_when_all_succeed() -> None:
    sink_a = RecordingSink()
    sink_b = RecordingSink()
    multi = MultiEventSink([sink_a, sink_b])
    event = {"event_type": "analysis.completed", "camera_id": "CAM1"}

    multi.publish(event)

    assert sink_a.events == [event]
    assert sink_b.events == [event]


def test_multi_event_sink_does_not_raise_when_at_least_one_sink_succeeds(
    caplog,
) -> None:
    recording = RecordingSink()
    failing = FailingSink()
    multi = MultiEventSink([failing, recording])
    event = {"event_type": "analysis.completed", "camera_id": "CAM1"}

    with caplog.at_level(logging.ERROR, logger="iris.events"):
        multi.publish(event)

    assert recording.events == [event]
    assert "FailingSink" in caplog.text
    assert "analysis.completed" in caplog.text
    assert "CAM1" in caplog.text


def test_multi_event_sink_raises_when_every_sink_fails() -> None:
    multi = MultiEventSink([FailingSink(), FailingSink()])
    event = {"event_type": "analysis.completed", "camera_id": "CAM1"}

    with pytest.raises(RuntimeError):
        multi.publish(event)


def test_multi_event_sink_raises_when_there_are_no_sinks() -> None:
    multi = MultiEventSink([])

    with pytest.raises(RuntimeError):
        multi.publish({"event_type": "analysis.completed"})


def test_multi_event_sink_filters_out_none_sinks() -> None:
    recording = RecordingSink()
    multi = MultiEventSink([recording, None])
    event = {"event_type": "analysis.completed", "camera_id": "CAM1"}

    multi.publish(event)

    assert recording.events == [event]


def test_multi_event_sink_close_closes_sinks_that_support_it_and_skips_others() -> None:
    recording = RecordingSink()
    failing = FailingSink()
    multi = MultiEventSink([recording, failing])

    multi.close()

    assert recording.closed is True
