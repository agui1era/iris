from __future__ import annotations

import csv
import logging
import math
import os
import re
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

from iris import config_store
from iris.models import SEVERITY_ORDER, AlibabaConfig, CameraConfig, ServiceConfig

logger = logging.getLogger(__name__)

_CAMERA_URL_PATTERNS = (
    re.compile(r"^CAM(\d+)_RTSP_URL$"),
    re.compile(r"^VITE_RTSP_URL_CAM(\d+)$"),
)
_TRUE_VALUES = {"1", "true", "yes", "y", "on", "si", "sí"}
_FALSE_VALUES = {"0", "false", "no", "n", "off"}
_OBSOLETE_GLOBAL_KEYS = {
    "CHANGE_THRESHOLD_PERCENT",
    "PIXEL_CHANGE_THRESHOLD",
    "DELTA_WIDTH",
    "DELTA_HEIGHT",
}
_OBSOLETE_CAMERA_OVERRIDE = re.compile(
    r"^CAM\d+_(?:FRAME_WIDTH|FRAME_HEIGHT|CHANGE_THRESHOLD_PERCENT)$"
)


class ConfigurationError(ValueError):
    """Raised when environment configuration is incomplete or invalid."""


def _value(env: Mapping[str, str], name: str, default: str | None = None) -> str:
    raw = env.get(name, default)
    if raw is None or not raw.strip():
        raise ConfigurationError(f"Falta la variable obligatoria {name}.")
    return raw.strip()


def _rtsp_url(env: Mapping[str, str], name: str) -> str:
    value = _value(env, name)
    if any(character.isspace() for character in value):
        raise ConfigurationError(f"{name} no puede contener espacios.")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ConfigurationError(f"{name} contiene una URL RTSP inválida.") from exc
    if parsed.scheme.lower() not in {"rtsp", "rtsps"} or not hostname:
        raise ConfigurationError(f"{name} debe ser una URL rtsp:// o rtsps:// válida.")
    if port is not None and not 1 <= port <= 65_535:
        raise ConfigurationError(f"{name} contiene un puerto fuera de rango.")
    return value


def _integer(
    env: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    raw = env.get(name, str(default)).strip()
    try:
        result = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} debe ser un entero; se recibió {raw!r}.") from exc
    if minimum is not None and result < minimum:
        raise ConfigurationError(f"{name} debe ser mayor o igual a {minimum}.")
    if maximum is not None and result > maximum:
        raise ConfigurationError(f"{name} debe ser menor o igual a {maximum}.")
    return result


def _number(
    env: Mapping[str, str],
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    raw = env.get(name, str(default)).strip()
    try:
        result = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} debe ser numérico; se recibió {raw!r}.") from exc
    if not math.isfinite(result):
        raise ConfigurationError(f"{name} debe ser un número finito; se recibió {raw!r}.")
    if minimum is not None and result < minimum:
        raise ConfigurationError(f"{name} debe ser mayor o igual a {minimum}.")
    if maximum is not None and result > maximum:
        raise ConfigurationError(f"{name} debe ser menor o igual a {maximum}.")
    return result


def _boolean(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name, str(default)).strip().lower()
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    raise ConfigurationError(f"{name} debe ser true/false, yes/no o 1/0; se recibió {raw!r}.")


def _camera_indices(env: Mapping[str, str]) -> list[int]:
    indices: set[int] = set()
    for key, value in env.items():
        if not value.strip():
            continue
        for pattern in _CAMERA_URL_PATTERNS:
            if match := pattern.fullmatch(key):
                indices.add(int(match.group(1)))
                break
    if not indices:
        raise ConfigurationError(
            "No hay cámaras configuradas. Define CAM1_RTSP_URL o VITE_RTSP_URL_CAM1."
        )
    enabled_indices = sorted(
        index for index in indices if _boolean(env, f"CAM{index}_ENABLED", True)
    )
    if not enabled_indices:
        raise ConfigurationError("Debe quedar al menos una cámara habilitada.")
    return enabled_indices


def _camera_rtsp_url(env: Mapping[str, str], index: int) -> str:
    primary = f"CAM{index}_RTSP_URL"
    compatible = f"VITE_RTSP_URL_CAM{index}"
    if env.get(primary, "").strip():
        return _rtsp_url(env, primary)
    logger.warning(
        "%s usa %s como compatibilidad temporal. Migra la URL a %s: "
        "las variables VITE_* pueden exponerse en el frontend.",
        f"CAM{index}",
        compatible,
        primary,
    )
    return _rtsp_url(env, compatible)


def _credentials_from_csv(path_value: str) -> dict[str, str]:
    path = Path(path_value).expanduser()
    try:
        mode = path.stat().st_mode
        if mode & 0o077:
            logger.warning(
                "El CSV de DashScope %s es legible por grupo/otros; restringe sus permisos a 0600.",
                path,
            )
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = csv.reader(stream)
            values = {
                row[0].strip(): row[1].strip()
                for row in rows
                if len(row) >= 2 and row[0].strip() and row[1].strip()
            }
    except (OSError, csv.Error) as exc:
        raise ConfigurationError(f"No se pudo leer DASHSCOPE_CREDENTIALS_CSV en {path}.") from exc
    return values


def _dashscope_credentials(source: Mapping[str, str]) -> tuple[str, str]:
    api_key = source.get("DASHSCOPE_API_KEY", "").strip()
    base_url = source.get("DASHSCOPE_BASE_URL", "").strip()
    csv_path = source.get("DASHSCOPE_CREDENTIALS_CSV", "").strip()
    if csv_path and (not api_key or not base_url):
        credentials = _credentials_from_csv(csv_path)
        api_key = api_key or credentials.get("apiKey", "")
        base_url = base_url or credentials.get("openAiCompatible", "")
    if not api_key:
        raise ConfigurationError(
            "Falta DASHSCOPE_API_KEY o un DASHSCOPE_CREDENTIALS_CSV con apiKey."
        )
    if not base_url:
        raise ConfigurationError(
            "Falta DASHSCOPE_BASE_URL o un DASHSCOPE_CREDENTIALS_CSV con openAiCompatible."
        )
    return api_key, base_url.rstrip("/")


def _auth_jwt_secret(source: Mapping[str, str]) -> str | None:
    # Optional at this level on purpose: iris-monitor never reads this value,
    # only the API process (iris.api.app) does, and it fails loudly at its own
    # startup if it's missing. Raising ConfigurationError here would force
    # iris-monitor deployments to define a secret they never use.
    raw = source.get("AUTH_JWT_SECRET", "").strip()
    return raw or None


def _cors_origins(source: Mapping[str, str]) -> tuple[str, ...]:
    default = ("http://localhost:5173",)
    raw = source.get("API_CORS_ORIGINS", "")
    if not raw.strip():
        return default
    origins = tuple(origin.strip() for origin in raw.split(",") if origin.strip())
    return origins or default


def _mongo_uri(source: Mapping[str, str]) -> str | None:
    raw = source.get("MONGO_URI", "").strip() or source.get("SENTINEX_MONGO_URI", "").strip()
    if not raw:
        return None
    if any(character.isspace() for character in raw):
        raise ConfigurationError("MONGO_URI no puede contener espacios.")
    if not raw.startswith(("mongodb://", "mongodb+srv://")):
        raise ConfigurationError("MONGO_URI debe comenzar con mongodb:// o mongodb+srv://.")
    return raw


def _warn_obsolete_pipeline_keys(source: Mapping[str, str]) -> None:
    obsolete = sorted(
        key
        for key, value in source.items()
        if value.strip()
        and (key in _OBSOLETE_GLOBAL_KEYS or _OBSOLETE_CAMERA_OVERRIDE.fullmatch(key) is not None)
    )
    if obsolete:
        logger.warning(
            "Se ignoraron opciones legacy de delta/override por cámara: %s. "
            "La resolución sigue siendo global y el delta ya no se usa.",
            ", ".join(obsolete),
        )


def load_config(
    env: Mapping[str, str] | None = None,
    *,
    dotenv_path: str | Path | None = None,
    config_db_path: str | Path | None = None,
) -> ServiceConfig:
    """Load and validate service configuration.

    When ``env`` is supplied it is treated as the complete environment, which keeps
    tests deterministic. Otherwise ``.env`` is loaded without overriding process
    variables.
    """

    config_revision = 0
    if env is None:
        selected_dotenv = (
            Path(dotenv_path).expanduser() if dotenv_path is not None else Path.cwd() / ".env"
        )
        load_dotenv(dotenv_path=selected_dotenv, override=False)
        selected_db_path = (
            Path(config_db_path).expanduser()
            if config_db_path is not None
            else Path(os.environ.get("IRIS_CONFIG_DB", "data/config.db")).expanduser()
        )
        source: Mapping[str, str]
        if config_store.is_config_initialized(selected_db_path):
            # SQLite stores the dynamic control-plane values while process
            # environment remains a safe fallback for deployment secrets and
            # infrastructure settings. Values persisted in SQLite always win.
            stored_mapping, config_revision = config_store.read_config_snapshot(selected_db_path)
            merged_source = dict(os.environ)
            merged_source.update(stored_mapping)
            source = merged_source
            logger.info("Configuración cargada desde SQLite en %s.", selected_db_path)
        else:
            source = os.environ
    else:
        source = env

    _warn_obsolete_pipeline_keys(source)
    default_width = _integer(source, "FRAME_WIDTH", 640, minimum=32, maximum=8192)
    default_height = _integer(source, "FRAME_HEIGHT", 360, minimum=32, maximum=8192)
    default_poll_interval = _number(
        source,
        "POLL_INTERVAL_SECONDS",
        30.0,
        minimum=30.0,
        maximum=86_400.0,
    )
    max_frame_pixels = _integer(
        source,
        "MAX_FRAME_PIXELS",
        2_621_440,
        minimum=1_024,
        maximum=16_777_216,
    )
    cameras: list[CameraConfig] = []
    for index in _camera_indices(source):
        prefix = f"CAM{index}"
        prompt = source.get(f"{prefix}_PROMPT", "").strip()
        if not prompt:
            raise ConfigurationError(f"Falta la variable obligatoria {prefix}_PROMPT.")
        cameras.append(
            CameraConfig(
                index=index,
                name=source.get(f"{prefix}_NAME", prefix).strip() or prefix,
                rtsp_url=_camera_rtsp_url(source, index),
                prompt=prompt,
                poll_interval_seconds=_number(
                    source,
                    f"{prefix}_POLL_INTERVAL_SECONDS",
                    default_poll_interval,
                    minimum=30.0,
                    maximum=86_400.0,
                ),
            )
        )

    if default_width * default_height > max_frame_pixels:
        raise ConfigurationError(
            f"FRAME_WIDTH x FRAME_HEIGHT solicita {default_width}x{default_height} "
            f"({default_width * default_height} píxeles), por encima de "
            f"MAX_FRAME_PIXELS={max_frame_pixels}."
        )

    api_key, base_url = _dashscope_credentials(source)
    try:
        parsed_base_url = urlsplit(base_url)
        base_port = parsed_base_url.port
    except ValueError as exc:
        raise ConfigurationError("DASHSCOPE_BASE_URL contiene una URL inválida.") from exc
    if parsed_base_url.scheme.lower() != "https" or not parsed_base_url.hostname:
        raise ConfigurationError("DASHSCOPE_BASE_URL debe ser una URL https:// válida.")
    if parsed_base_url.username or parsed_base_url.password:
        raise ConfigurationError("DASHSCOPE_BASE_URL no puede contener credenciales.")
    if parsed_base_url.query or parsed_base_url.fragment:
        raise ConfigurationError("DASHSCOPE_BASE_URL no puede contener query ni fragment.")
    if base_port is not None and not 1 <= base_port <= 65_535:
        raise ConfigurationError("DASHSCOPE_BASE_URL contiene un puerto fuera de rango.")
    if not parsed_base_url.path.rstrip("/").endswith("/compatible-mode/v1"):
        raise ConfigurationError("DASHSCOPE_BASE_URL debe terminar en /compatible-mode/v1.")
    if not parsed_base_url.hostname.lower().endswith(".aliyuncs.com"):
        raise ConfigurationError(
            "DASHSCOPE_BASE_URL debe usar un endpoint oficial bajo .aliyuncs.com."
        )

    transport = source.get("RTSP_TRANSPORT", "tcp").strip().lower()
    if transport not in {"tcp", "udp"}:
        raise ConfigurationError("RTSP_TRANSPORT debe ser tcp o udp.")

    save_image_min_severity = source.get("SAVE_IMAGE_MIN_SEVERITY", "high").strip().lower()
    if save_image_min_severity not in SEVERITY_ORDER:
        raise ConfigurationError(
            "SAVE_IMAGE_MIN_SEVERITY debe ser uno de: "
            f"{', '.join(SEVERITY_ORDER)}; se recibió {save_image_min_severity!r}."
        )

    mongo_uri = _mongo_uri(source)
    mongo_database = (
        source.get("MONGO_DATABASE", "").strip()
        or source.get("SENTINEX_MONGO_DB", "").strip()
        or "iris"
    )
    mongo_detection_collection = (
        source.get("MONGO_DETECTION_COLLECTION", "").strip()
        or source.get("SENTINEX_MONGO_DETECTION_COLLECTION", "").strip()
        or "iris_detections"
    )

    events_path_raw = source.get("EVENTS_JSONL_PATH", "data/events.jsonl").strip()
    return ServiceConfig(
        poll_interval_seconds=default_poll_interval,
        reconnect_interval_seconds=_number(source, "RTSP_RECONNECT_SECONDS", 5.0, minimum=0.1),
        frame_stale_after_seconds=_number(source, "FRAME_STALE_AFTER_SECONDS", 15.0, minimum=0.1),
        analysis_cooldown_seconds=_number(source, "ANALYSIS_COOLDOWN_SECONDS", 15.0, minimum=0.0),
        max_api_calls_per_minute=_integer(
            source, "MAX_API_CALLS_PER_MINUTE", 60, minimum=0, maximum=100_000
        ),
        max_frame_pixels=max_frame_pixels,
        jpeg_quality=_integer(source, "JPEG_QUALITY", 82, minimum=1, maximum=100),
        max_concurrent_analyses=_integer(
            source, "MAX_CONCURRENT_ANALYSES", 1, minimum=1, maximum=128
        ),
        rtsp_transport=transport,
        rtsp_open_timeout_ms=_integer(source, "RTSP_OPEN_TIMEOUT_MS", 10_000, minimum=100),
        rtsp_read_timeout_ms=_integer(source, "RTSP_READ_TIMEOUT_MS", 10_000, minimum=100),
        save_captures=_boolean(source, "SAVE_CAPTURES", True),
        capture_dir=Path(source.get("CAPTURE_DIR", "data/captures")).expanduser(),
        capture_retention_days=_number(
            source, "CAPTURE_RETENTION_DAYS", 7.0, minimum=0.0, maximum=3_650.0
        ),
        capture_max_files_per_camera=_integer(
            source,
            "CAPTURE_MAX_FILES_PER_CAMERA",
            1_000,
            minimum=0,
            maximum=10_000_000,
        ),
        events_jsonl_path=Path(events_path_raw).expanduser() if events_path_raw else None,
        events_max_bytes=_integer(
            source,
            "EVENTS_MAX_BYTES",
            50_000_000,
            minimum=0,
            maximum=10_000_000_000,
        ),
        events_backup_count=_integer(source, "EVENTS_BACKUP_COUNT", 5, minimum=1, maximum=100),
        log_level=source.get("LOG_LEVEL", "INFO").strip().upper(),
        cameras=tuple(cameras),
        alibaba=AlibabaConfig(
            api_key=api_key,
            base_url=base_url,
            model=source.get("DASHSCOPE_MODEL", "qwen3.6-flash").strip() or "qwen3.6-flash",
            timeout_seconds=_number(
                source,
                "DASHSCOPE_TIMEOUT_SECONDS",
                45.0,
                minimum=1.0,
                maximum=300.0,
            ),
            max_retries=_integer(source, "DASHSCOPE_MAX_RETRIES", 3, minimum=0, maximum=10),
            max_completion_tokens=_integer(
                source,
                "DASHSCOPE_MAX_COMPLETION_TOKENS",
                512,
                minimum=32,
                maximum=32_768,
            ),
        ),
        save_image_min_severity=save_image_min_severity,
        mongo_uri=mongo_uri,
        mongo_database=mongo_database,
        mongo_detection_collection=mongo_detection_collection,
        auth_jwt_secret=_auth_jwt_secret(source),
        auth_jwt_expires_minutes=_integer(source, "AUTH_JWT_EXPIRES_MINUTES", 480, minimum=5),
        api_cors_origins=_cors_origins(source),
        api_host=source.get("API_HOST", "0.0.0.0").strip() or "0.0.0.0",
        api_port=_integer(source, "API_PORT", 8000, minimum=1, maximum=65_535),
        frame_width=default_width,
        frame_height=default_height,
        config_revision=config_revision,
    )


def config_mapping(
    config: ServiceConfig,
    *,
    include_secrets_and_infrastructure: bool = True,
) -> dict[str, str]:
    """Serialize a validated config using the canonical environment keys.

    The dashboard seeds only the dynamic subset. The complete form exists for
    in-memory validation of a candidate mapping and is never returned by an
    API response.
    """

    values = {
        "POLL_INTERVAL_SECONDS": str(config.poll_interval_seconds),
        "FRAME_WIDTH": str(config.frame_width),
        "FRAME_HEIGHT": str(config.frame_height),
        "JPEG_QUALITY": str(config.jpeg_quality),
        "MAX_CONCURRENT_ANALYSES": str(config.max_concurrent_analyses),
        "ANALYSIS_COOLDOWN_SECONDS": str(config.analysis_cooldown_seconds),
        "MAX_API_CALLS_PER_MINUTE": str(config.max_api_calls_per_minute),
        "MAX_FRAME_PIXELS": str(config.max_frame_pixels),
        "FRAME_STALE_AFTER_SECONDS": str(config.frame_stale_after_seconds),
        "DASHSCOPE_MODEL": config.alibaba.model,
        "DASHSCOPE_BASE_URL": config.alibaba.base_url,
        "DASHSCOPE_TIMEOUT_SECONDS": str(config.alibaba.timeout_seconds),
        "DASHSCOPE_MAX_RETRIES": str(config.alibaba.max_retries),
        "DASHSCOPE_MAX_COMPLETION_TOKENS": str(config.alibaba.max_completion_tokens),
        "SAVE_IMAGE_MIN_SEVERITY": config.save_image_min_severity,
    }
    for camera in config.cameras:
        prefix = camera.identifier
        values.update(
            {
                f"{prefix}_ENABLED": "true",
                f"{prefix}_NAME": camera.name,
                f"{prefix}_RTSP_URL": camera.rtsp_url,
                f"{prefix}_PROMPT": camera.prompt,
                f"{prefix}_POLL_INTERVAL_SECONDS": str(camera.poll_interval_seconds),
            }
        )
    if include_secrets_and_infrastructure:
        values.update(
            {
                "DASHSCOPE_API_KEY": config.alibaba.api_key,
                "RTSP_TRANSPORT": config.rtsp_transport,
                "RTSP_RECONNECT_SECONDS": str(config.reconnect_interval_seconds),
                "RTSP_OPEN_TIMEOUT_MS": str(config.rtsp_open_timeout_ms),
                "RTSP_READ_TIMEOUT_MS": str(config.rtsp_read_timeout_ms),
                "SAVE_CAPTURES": str(config.save_captures).lower(),
                "CAPTURE_DIR": str(config.capture_dir),
                "CAPTURE_RETENTION_DAYS": str(config.capture_retention_days),
                "CAPTURE_MAX_FILES_PER_CAMERA": str(config.capture_max_files_per_camera),
                "EVENTS_JSONL_PATH": (
                    str(config.events_jsonl_path) if config.events_jsonl_path else ""
                ),
                "EVENTS_MAX_BYTES": str(config.events_max_bytes),
                "EVENTS_BACKUP_COUNT": str(config.events_backup_count),
                "LOG_LEVEL": config.log_level,
                "MONGO_DATABASE": config.mongo_database,
                "MONGO_DETECTION_COLLECTION": config.mongo_detection_collection,
                "AUTH_JWT_EXPIRES_MINUTES": str(config.auth_jwt_expires_minutes),
                "API_CORS_ORIGINS": ",".join(config.api_cors_origins),
                "API_HOST": config.api_host,
                "API_PORT": str(config.api_port),
            }
        )
        if config.mongo_uri is not None:
            values["MONGO_URI"] = config.mongo_uri
        if config.auth_jwt_secret is not None:
            values["AUTH_JWT_SECRET"] = config.auth_jwt_secret
    return values


def sanitized_config(config: ServiceConfig) -> dict[str, object]:
    """Return configuration safe to display in logs or ``--check-config``."""

    return {
        "poll_interval_seconds": config.poll_interval_seconds,
        "config_revision": config.config_revision,
        "reconnect_interval_seconds": config.reconnect_interval_seconds,
        "frame_stale_after_seconds": config.frame_stale_after_seconds,
        "frame_resolution": f"{config.frame_width}x{config.frame_height}",
        "analysis_cooldown_seconds": config.analysis_cooldown_seconds,
        "max_api_calls_per_minute": config.max_api_calls_per_minute,
        "max_frame_pixels": config.max_frame_pixels,
        "jpeg_quality": config.jpeg_quality,
        "max_concurrent_analyses": config.max_concurrent_analyses,
        "rtsp_transport": config.rtsp_transport,
        "save_captures": config.save_captures,
        "capture_dir": str(config.capture_dir),
        "capture_retention_days": config.capture_retention_days,
        "capture_max_files_per_camera": config.capture_max_files_per_camera,
        "save_image_min_severity": config.save_image_min_severity,
        "events_jsonl_path": (str(config.events_jsonl_path) if config.events_jsonl_path else None),
        "events_max_bytes": config.events_max_bytes,
        "events_backup_count": config.events_backup_count,
        "dashscope_base_url": config.alibaba.base_url,
        "dashscope_model": config.alibaba.model,
        "mongo_configured": config.mongo_uri is not None,
        "mongo_database": config.mongo_database,
        "mongo_detection_collection": config.mongo_detection_collection,
        "auth_configured": config.auth_jwt_secret is not None,
        "auth_jwt_expires_minutes": config.auth_jwt_expires_minutes,
        "api_cors_origins": list(config.api_cors_origins),
        "api_host": config.api_host,
        "api_port": config.api_port,
        "cameras": [
            {
                "id": camera.identifier,
                "name": camera.name,
                "rtsp_url": "<redacted>",
                "prompt": "<configured>",
                "poll_interval_seconds": camera.poll_interval_seconds,
            }
            for camera in config.cameras
        ],
    }
