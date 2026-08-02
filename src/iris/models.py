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
    # Severidad mínima para disparar una notificación de esta cámara.
    notification_threshold: str = "high"
    # Interruptor por cámara. El interruptor maestro de ServiceConfig y las
    # credenciales globales siguen siendo necesarios para enviar.
    notifications_enabled: bool = True

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
    change_threshold_percent: float = 0.0
    pixel_change_threshold: int = 24
    delta_width: int = 160
    delta_height: int = 90
    mongo_uri: str | None = None
    mongo_database: str = "iris"
    mongo_detection_collection: str = "iris_detections"
    # Un único bot/chat global; qué cámara notifica lo decide su propio
    # notification_threshold. Sin ambas variables, el envío queda desactivado.
    # telegram_enabled es un interruptor maestro aparte: permite guardar
    # credenciales sin activar el envío todavía.
    telegram_enabled: bool = True
    telegram_bot_token: str | None = field(default=None, repr=False)
    telegram_chat_id: str | None = None
    # Evita inundar Telegram con el mismo evento. Las detecciones siguen
    # persistiendo normalmente; sólo se agrupa el canal de salida.
    telegram_dedup_cooldown_seconds: int = 600
    history_chat_enabled: bool = True
    openai_api_key: str | None = field(default=None, repr=False)
    history_chat_model: str = "gpt-4.1-mini"
    history_chat_max_range_days: int = 31
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
