from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

Frame = NDArray[np.uint8]

SEVERITY_ORDER: tuple[str, ...] = ("none", "info", "low", "medium", "high", "critical")


@dataclass(frozen=True, slots=True)
class CameraConfig:
    index: int
    name: str
    rtsp_url: str = field(repr=False)
    prompt: str = field(repr=False)
    poll_interval_seconds: float = 30.0

    @property
    def identifier(self) -> str:
        return f"CAM{self.index}"


@dataclass(frozen=True, slots=True)
class AlibabaConfig:
    api_key: str = field(repr=False)
    base_url: str
    model: str
    timeout_seconds: float
    max_retries: int
    max_completion_tokens: int


@dataclass(frozen=True, slots=True)
class ServiceConfig:
    poll_interval_seconds: float
    reconnect_interval_seconds: float
    frame_stale_after_seconds: float
    analysis_cooldown_seconds: float
    max_api_calls_per_minute: int
    max_frame_pixels: int
    jpeg_quality: int
    max_concurrent_analyses: int
    rtsp_transport: str
    rtsp_open_timeout_ms: int
    rtsp_read_timeout_ms: int
    save_captures: bool
    capture_dir: Path
    capture_retention_days: float
    capture_max_files_per_camera: int
    events_jsonl_path: Path | None
    events_max_bytes: int
    events_backup_count: int
    log_level: str
    cameras: tuple[CameraConfig, ...]
    alibaba: AlibabaConfig
    save_image_min_severity: str = "high"
    mongo_uri: str | None = None
    mongo_database: str = "iris"
    mongo_detection_collection: str = "iris_detections"
    auth_jwt_secret: str | None = None
    auth_jwt_expires_minutes: int = 480
    api_cors_origins: tuple[str, ...] = ("http://localhost:5173",)
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    frame_width: int = 640
    frame_height: int = 360
    config_revision: int = 0


@dataclass(frozen=True, slots=True)
class FrameSnapshot:
    frame: Frame
    captured_at: datetime
    sequence: int


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    data: dict[str, Any]
    raw_text: str
    model: str
    usage: dict[str, Any] | None = None
    request_id: str | None = None
