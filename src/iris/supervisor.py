from __future__ import annotations

import fcntl
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from iris import config_store
from iris.config import ConfigurationError, load_config
from iris.models import ServiceConfig

logger = logging.getLogger(__name__)


class MonitorGeneration(Protocol):
    def run(self) -> None: ...

    def request_stop(self) -> None: ...


GenerationFactory = Callable[[ServiceConfig], MonitorGeneration]


class MonitorAlreadyRunning(RuntimeError):
    pass


class MonitoringSupervisor:
    """Apply SQLite configuration revisions without overlapping RTSP readers."""

    def __init__(
        self,
        *,
        config_db_path: Path,
        dotenv_path: Path,
        generation_factory: GenerationFactory,
        check_interval_seconds: float = 1.0,
    ) -> None:
        self._config_db_path = config_db_path
        self._dotenv_path = dotenv_path
        self._generation_factory = generation_factory
        self._check_interval_seconds = check_interval_seconds
        self._stop_event = threading.Event()
        self._current_lock = threading.Lock()
        self._current: MonitorGeneration | None = None

    def request_stop(self) -> None:
        self._stop_event.set()
        with self._current_lock:
            current = self._current
        if current is not None:
            current.request_stop()

    def run(self) -> None:
        lock_descriptor = self._acquire_instance_lock()
        try:
            self._run_locked()
        finally:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            os.close(lock_descriptor)

    def _run_locked(self) -> None:
        while not self._stop_event.is_set():
            config = load_config(
                dotenv_path=self._dotenv_path,
                config_db_path=self._config_db_path,
            )
            applied_revision = config.config_revision
            generation = self._generation_factory(config)
            with self._current_lock:
                self._current = generation

            failure: list[BaseException] = []

            def run_generation(
                current: MonitorGeneration = generation,
                failures: list[BaseException] = failure,
            ) -> None:
                try:
                    current.run()
                except BaseException as exc:
                    failures.append(exc)

            thread = threading.Thread(
                target=run_generation,
                name=f"iris-generation-r{applied_revision}",
            )
            thread.start()
            reload_requested = False

            try:
                while thread.is_alive() and not self._stop_event.wait(self._check_interval_seconds):
                    desired_revision = config_store.read_config_revision(self._config_db_path)
                    if desired_revision == applied_revision:
                        continue
                    try:
                        # Validate the complete new snapshot before touching the
                        # healthy generation currently monitoring the cameras.
                        load_config(
                            dotenv_path=self._dotenv_path,
                            config_db_path=self._config_db_path,
                        )
                    except ConfigurationError:
                        logger.exception(
                            "La revisión %d es inválida; se mantiene activa la revisión %d.",
                            desired_revision,
                            applied_revision,
                        )
                        continue
                    logger.info(
                        "Aplicando configuración r%d (actual r%d).",
                        desired_revision,
                        applied_revision,
                    )
                    reload_requested = True
                    generation.request_stop()
                    break
            finally:
                # A transient SQLite/I/O error in the revision watcher must
                # never release the instance lock while an RTSP generation is
                # still alive.
                if thread.is_alive():
                    generation.request_stop()
                thread.join()
                with self._current_lock:
                    self._current = None

            if failure:
                raise RuntimeError("La generación de monitoreo terminó con error.") from failure[0]
            if self._stop_event.is_set():
                return
            if not reload_requested:
                raise RuntimeError("La generación de monitoreo terminó inesperadamente.")

    def _acquire_instance_lock(self) -> int:
        lock_path = self._config_db_path.with_name(f"{self._config_db_path.name}.monitor.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise MonitorAlreadyRunning(
                "Ya existe otro iris-monitor usando esta base de configuración."
            ) from exc
        return descriptor
