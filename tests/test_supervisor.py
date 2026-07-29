from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import iris.supervisor as supervisor_module
from iris.supervisor import MonitoringSupervisor


def _wait_until(predicate, *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.005)
    assert predicate()


class _Generation:
    def __init__(self, revision: int, order: list[str]) -> None:
        self.revision = revision
        self.order = order
        self.started = threading.Event()
        self.stop_requested = threading.Event()

    def run(self) -> None:
        self.order.append(f"start-{self.revision}")
        self.started.set()
        self.stop_requested.wait()
        self.order.append(f"stop-{self.revision}")

    def request_stop(self) -> None:
        self.stop_requested.set()


def test_supervisor_applies_new_revision_without_overlapping_generations(
    monkeypatch,
    tmp_path: Path,
) -> None:
    desired = [1]
    order: list[str] = []
    generations: list[_Generation] = []

    def fake_load_config(**_kwargs: Any):
        return SimpleNamespace(config_revision=desired[0])

    def factory(config) -> _Generation:
        generation = _Generation(config.config_revision, order)
        generations.append(generation)
        return generation

    monkeypatch.setattr(supervisor_module, "load_config", fake_load_config)
    monkeypatch.setattr(
        supervisor_module.config_store,
        "read_config_revision",
        lambda _path: desired[0],
    )
    supervisor = MonitoringSupervisor(
        config_db_path=tmp_path / "config.db",
        dotenv_path=tmp_path / ".env",
        generation_factory=factory,
        check_interval_seconds=0.01,
    )
    failures: list[BaseException] = []

    def run() -> None:
        try:
            supervisor.run()
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    _wait_until(lambda: len(generations) == 1 and generations[0].started.is_set())

    desired[0] = 2
    _wait_until(lambda: len(generations) == 2 and generations[1].started.is_set())
    supervisor.request_stop()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert failures == []
    assert order == ["start-1", "stop-1", "start-2", "stop-2"]


def test_supervisor_surfaces_unexpected_generation_exit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class ExitingGeneration:
        def run(self) -> None:
            return None

        def request_stop(self) -> None:
            return None

    monkeypatch.setattr(
        supervisor_module,
        "load_config",
        lambda **_kwargs: SimpleNamespace(config_revision=1),
    )
    supervisor = MonitoringSupervisor(
        config_db_path=tmp_path / "config.db",
        dotenv_path=tmp_path / ".env",
        generation_factory=lambda _config: ExitingGeneration(),
        check_interval_seconds=0.01,
    )

    try:
        supervisor.run()
    except RuntimeError as exc:
        assert "inesperadamente" in str(exc)
    else:
        raise AssertionError("El supervisor debía reportar el fin inesperado.")


def test_supervisor_stops_generation_when_revision_read_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    order: list[str] = []
    generation = _Generation(1, order)
    monkeypatch.setattr(
        supervisor_module,
        "load_config",
        lambda **_kwargs: SimpleNamespace(config_revision=1),
    )
    monkeypatch.setattr(
        supervisor_module.config_store,
        "read_config_revision",
        lambda _path: (_ for _ in ()).throw(OSError("sqlite unavailable")),
    )
    supervisor = MonitoringSupervisor(
        config_db_path=tmp_path / "config.db",
        dotenv_path=tmp_path / ".env",
        generation_factory=lambda _config: generation,
        check_interval_seconds=0.01,
    )

    try:
        supervisor.run()
    except OSError as exc:
        assert "sqlite unavailable" in str(exc)
    else:
        raise AssertionError("El supervisor debía propagar el error de SQLite.")

    assert generation.stop_requested.is_set()
    assert order == ["start-1", "stop-1"]
