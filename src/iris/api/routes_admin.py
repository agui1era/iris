from __future__ import annotations

import re
from dataclasses import asdict
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from iris import config_store
from iris.config import ConfigurationError, config_mapping, load_config
from iris.models import CameraConfig, ServiceConfig
from iris.users_store import (
    UsersStoreError,
    create_user,
    get_user,
    list_users,
    set_active,
    set_role,
)

from .security import AdminUser

router = APIRouter()
_PRIVATE_NO_STORE = "private, no-store"

# Mapea los campos editables de cámara a CAMn_<sufijo>. La resolución sigue
# siendo global, pero cada cámara controla su propio intervalo de polling.
_CAMERA_FIELD_SUFFIX = {
    "name": "NAME",
    "rtsp_url": "RTSP_URL",
    "prompt": "PROMPT",
    "poll_interval_seconds": "POLL_INTERVAL_SECONDS",
    "notification_threshold": "NOTIFICATION_THRESHOLD",
}


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    created_at: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str


class UpdateUserRequest(BaseModel):
    role: str | None = None
    is_active: bool | None = None


class SettingsResponse(BaseModel):
    revision: int
    frame_width: int
    frame_height: int
    jpeg_quality: int
    max_api_calls_per_minute: int
    save_image_min_severity: str
    change_threshold_percent: float
    telegram_enabled: bool
    telegram_configured: bool
    alibaba_api_key_configured: bool
    alibaba_base_url: str
    alibaba_model: str
    alibaba_timeout_seconds: float
    alibaba_max_retries: int
    alibaba_max_completion_tokens: int


class SettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=0)
    frame_width: int | None = Field(default=None, ge=32, le=8_192)
    frame_height: int | None = Field(default=None, ge=32, le=8_192)
    jpeg_quality: int | None = Field(default=None, ge=1, le=100)
    max_api_calls_per_minute: int | None = Field(default=None, ge=0, le=100_000)
    save_image_min_severity: str | None = None
    change_threshold_percent: float | None = Field(default=None, ge=0, le=100)
    telegram_enabled: bool | None = None
    alibaba_api_key: SecretStr | None = None
    alibaba_base_url: str | None = Field(default=None, min_length=1, max_length=2_048)
    alibaba_model: str | None = Field(default=None, min_length=1, max_length=200)
    alibaba_timeout_seconds: float | None = Field(default=None, ge=1, le=300)
    alibaba_max_retries: int | None = Field(default=None, ge=0, le=10)
    alibaba_max_completion_tokens: int | None = Field(default=None, ge=32, le=32_768)

    @field_validator("alibaba_base_url")
    @classmethod
    def require_official_alibaba_endpoint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = urlsplit(value.strip())
            port = parsed.port
        except ValueError as exc:
            raise ValueError("La Base URL de Alibaba no es válida.") from exc
        host = parsed.hostname
        if (
            parsed.scheme.lower() != "https"
            or host is None
            or not host.lower().endswith(".aliyuncs.com")
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or (port is not None and not 1 <= port <= 65_535)
            or not parsed.path.rstrip("/").endswith("/compatible-mode/v1")
        ):
            raise ValueError(
                "La Base URL editable debe ser un endpoint oficial HTTPS de Alibaba "
                "terminado en .aliyuncs.com/compatible-mode/v1."
            )
        return value.strip().rstrip("/")


class CameraResponse(BaseModel):
    index: int
    id: str
    name: str
    rtsp_url: str
    prompt: str
    poll_interval_seconds: float
    # Severidad mínima para notificar (Telegram u otro canal futuro); sólo el
    # umbral se guarda hoy, el envío en sí todavía no está implementado.
    notification_threshold: str


class CreateCameraRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    rtsp_url: str
    prompt: str
    poll_interval_seconds: float = Field(default=30.0, ge=10, le=86_400)
    notification_threshold: str = "high"


class UpdateCameraRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    rtsp_url: str | None = None
    prompt: str | None = None
    poll_interval_seconds: float | None = Field(default=None, ge=30, le=86_400)
    notification_threshold: str | None = None


def _users_store_error_status(exc: UsersStoreError) -> int:
    # users_store raises the same UsersStoreError for "duplicate username" and
    # for "invalid role" / "unknown username"; the message text is the only
    # way to tell them apart without changing that module's contract.
    message = str(exc)
    if "ya existe" in message:
        return status.HTTP_409_CONFLICT
    if "no existe" in message:
        return status.HTTP_404_NOT_FOUND
    return status.HTTP_400_BAD_REQUEST


@router.get("/users", response_model=list[UserResponse])
def get_users(request: Request, admin: AdminUser) -> list[UserResponse]:
    users = list_users(request.app.state.users_db_path)
    return [UserResponse(**asdict(user)) for user in users]


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def post_user(
    body: CreateUserRequest,
    request: Request,
    admin: AdminUser,
) -> UserResponse:
    try:
        user = create_user(request.app.state.users_db_path, body.username, body.password, body.role)
    except UsersStoreError as exc:
        raise HTTPException(status_code=_users_store_error_status(exc), detail=str(exc)) from exc
    return UserResponse(**asdict(user))


@router.patch("/users/{username}", response_model=UserResponse)
def patch_user(
    username: str,
    body: UpdateUserRequest,
    request: Request,
    admin: AdminUser,
) -> UserResponse:
    db_path = request.app.state.users_db_path
    if body.role is None and body.is_active is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes indicar 'role' y/o 'is_active'.",
        )
    try:
        if body.role is not None:
            set_role(db_path, username, body.role)
        if body.is_active is not None:
            set_active(db_path, username, body.is_active)
    except UsersStoreError as exc:
        raise HTTPException(status_code=_users_store_error_status(exc), detail=str(exc)) from exc
    updated = get_user(db_path, username)
    assert updated is not None  # set_role/set_active above already confirmed existence
    return UserResponse(**asdict(updated))


_SETTINGS_FIELD_KEY = {
    "frame_width": "FRAME_WIDTH",
    "frame_height": "FRAME_HEIGHT",
    "jpeg_quality": "JPEG_QUALITY",
    "max_api_calls_per_minute": "MAX_API_CALLS_PER_MINUTE",
    "save_image_min_severity": "SAVE_IMAGE_MIN_SEVERITY",
    "change_threshold_percent": "CHANGE_THRESHOLD_PERCENT",
    "telegram_enabled": "ENABLE_TELEGRAM",
    "alibaba_base_url": "DASHSCOPE_BASE_URL",
    "alibaba_model": "DASHSCOPE_MODEL",
    "alibaba_timeout_seconds": "DASHSCOPE_TIMEOUT_SECONDS",
    "alibaba_max_retries": "DASHSCOPE_MAX_RETRIES",
    "alibaba_max_completion_tokens": "DASHSCOPE_MAX_COMPLETION_TOKENS",
}


def _settings_response(config: ServiceConfig, revision: int) -> SettingsResponse:
    return SettingsResponse(
        revision=revision,
        frame_width=config.frame_width,
        frame_height=config.frame_height,
        jpeg_quality=config.jpeg_quality,
        max_api_calls_per_minute=config.max_api_calls_per_minute,
        save_image_min_severity=config.save_image_min_severity,
        change_threshold_percent=config.change_threshold_percent,
        telegram_enabled=config.telegram_enabled,
        telegram_configured=bool(config.telegram_bot_token and config.telegram_chat_id),
        alibaba_api_key_configured=bool(config.alibaba.api_key.strip()),
        alibaba_base_url=config.alibaba.base_url,
        alibaba_model=config.alibaba.model,
        alibaba_timeout_seconds=config.alibaba.timeout_seconds,
        alibaba_max_retries=config.alibaba.max_retries,
        alibaba_max_completion_tokens=config.alibaba.max_completion_tokens,
    )


@router.get("/settings", response_model=SettingsResponse)
def get_settings(request: Request, admin: AdminUser) -> SettingsResponse:
    # Siempre recarga desde disco (ver _fresh_config): app.state.config es la
    # foto tomada al arrancar la API y queda obsoleta en cuanto se edita algo
    # aquí o en /admin/cameras.
    config = _fresh_config(request)
    return _settings_response(config, config.config_revision)


@router.patch("/settings", response_model=SettingsResponse)
def patch_settings(
    body: SettingsUpdateRequest,
    request: Request,
    admin: AdminUser,
) -> SettingsResponse:
    db_path = request.app.state.users_db_path
    raw = body.model_dump(exclude_unset=True, exclude_none=True)
    expected_revision = raw.pop("revision")
    secret = raw.pop("alibaba_api_key", None)
    secret_was_supplied = secret is not None
    updates = raw
    new_values = {_SETTINGS_FIELD_KEY[field]: str(value) for field, value in updates.items()}
    if secret is not None:
        api_key = secret.get_secret_value().strip()
        if api_key:
            new_values["DASHSCOPE_API_KEY"] = api_key

    if not new_values and not secret_was_supplied:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes indicar al menos un campo para actualizar.",
        )
    if not new_values:
        # An empty/whitespace API-key input deliberately means "keep the
        # existing secret". It is a successful no-op and does not advance the
        # revision.
        return _settings_response(
            (config := _fresh_config(request)),
            config.config_revision,
        )

    try:
        config_store.mutate_config_mapping(
            db_path,
            values=new_values,
            expected_revision=expected_revision,
            validator=_candidate_validator(request),
        )
    except config_store.ConfigRevisionConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    config = _fresh_config(request)
    return _settings_response(config, config.config_revision)


def _camera_key(index: int, field: str) -> str:
    return f"CAM{index}_{_CAMERA_FIELD_SUFFIX[field]}"


def _fresh_config(request: Request) -> ServiceConfig:
    # Siempre recarga desde disco: app.state.config es la foto tomada al
    # arrancar la API y queda obsoleta en cuanto se agrega/edita/borra una
    # cámara. Reusar load_config() aquí reaprovecha gratis toda su validación
    # (forma de la URL RTSP, prompt no vacío, resolución global vs
    # MAX_FRAME_PIXELS, proveedor Alibaba, etc.) en vez de duplicarla.
    try:
        return load_config(config_db_path=request.app.state.users_db_path)
    except ConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _candidate_validator(request: Request):
    # Static deployment settings/secrets remain outside the editable surface.
    # They are supplied only in-memory so load_config can validate the complete
    # candidate while mutate_config_mapping holds its transaction.
    baseline = config_mapping(
        _fresh_config(request),
        include_secrets_and_infrastructure=True,
    )

    def validate(candidate: dict[str, str]) -> None:
        merged = dict(baseline)
        merged.update(candidate)
        load_config(env=merged)

    return validate


def _camera_response(camera: CameraConfig) -> CameraResponse:
    return CameraResponse(
        index=camera.index,
        id=camera.identifier,
        name=camera.name,
        rtsp_url=camera.rtsp_url,
        prompt=camera.prompt,
        poll_interval_seconds=camera.poll_interval_seconds,
        notification_threshold=camera.notification_threshold,
    )


def _disable_secret_response_cache(response: Response) -> None:
    # Las respuestas de cámaras contienen la URL RTSP completa, incluidas
    # credenciales si vienen embebidas. El navegador puede mostrarlas al
    # administrador, pero no debe conservarlas en su caché.
    response.headers["Cache-Control"] = _PRIVATE_NO_STORE


def _require_camera(config: ServiceConfig, index: int) -> CameraConfig:
    for camera in config.cameras:
        if camera.index == index:
            return camera
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"CAM{index} no está configurada.",
    )


@router.get("/cameras", response_model=list[CameraResponse])
def get_cameras(
    request: Request,
    response: Response,
    admin: AdminUser,
) -> list[CameraResponse]:
    _disable_secret_response_cache(response)
    config = _fresh_config(request)
    return [_camera_response(camera) for camera in config.cameras]


@router.post("/cameras", response_model=CameraResponse, status_code=status.HTTP_201_CREATED)
def post_camera(
    body: CreateCameraRequest,
    request: Request,
    response: Response,
    admin: AdminUser,
) -> CameraResponse:
    _disable_secret_response_cache(response)
    db_path = request.app.state.users_db_path
    _fresh_config(request)
    current_mapping, current_revision = config_store.read_config_snapshot(db_path)
    used_indices = {
        int(match.group(1)) for key in current_mapping if (match := re.match(r"^CAM(\d+)_", key))
    }
    index = max(used_indices, default=0) + 1

    values: dict[str, str] = {
        f"CAM{index}_ENABLED": "true",
        _camera_key(index, "name"): body.name,
        _camera_key(index, "rtsp_url"): body.rtsp_url,
        _camera_key(index, "prompt"): body.prompt,
        _camera_key(index, "poll_interval_seconds"): str(body.poll_interval_seconds),
        _camera_key(index, "notification_threshold"): body.notification_threshold,
    }

    try:
        config_store.mutate_config_mapping(
            db_path,
            values=values,
            expected_revision=current_revision,
            validator=_candidate_validator(request),
        )
    except config_store.ConfigRevisionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Otra cámara fue creada al mismo tiempo; vuelve a intentarlo.",
        ) from exc
    except ConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    new_config = _fresh_config(request)
    created = _require_camera(new_config, index)
    return _camera_response(created)


@router.patch("/cameras/{index}", response_model=CameraResponse)
def patch_camera(
    index: int,
    body: UpdateCameraRequest,
    request: Request,
    response: Response,
    admin: AdminUser,
) -> CameraResponse:
    _disable_secret_response_cache(response)
    db_path = request.app.state.users_db_path
    config = _fresh_config(request)
    _require_camera(config, index)

    updates = body.model_dump(exclude_unset=True, exclude_none=True)
    if updates.get("rtsp_url", None) == "":
        updates.pop("rtsp_url")
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes indicar al menos un campo para actualizar.",
        )

    new_values = {_camera_key(index, field): str(value) for field, value in updates.items()}
    try:
        config_store.mutate_config_mapping(
            db_path,
            values=new_values,
            validator=_candidate_validator(request),
        )
    except ConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    new_config = _fresh_config(request)
    updated = _require_camera(new_config, index)
    return _camera_response(updated)


@router.delete("/cameras/{index}", response_model=CameraResponse)
def delete_camera(
    index: int,
    request: Request,
    response: Response,
    admin: AdminUser,
) -> CameraResponse:
    _disable_secret_response_cache(response)
    db_path = request.app.state.users_db_path
    config = _fresh_config(request)
    deleted = _camera_response(_require_camera(config, index))

    prefix = f"CAM{index}_"
    current_mapping = config_store.read_config_mapping(db_path)
    camera_keys = [key for key in current_mapping if key.startswith(prefix)]
    try:
        config_store.mutate_config_mapping(
            db_path,
            values={f"CAM{index}_ENABLED": "false"},
            delete_keys=camera_keys,
            validator=_candidate_validator(request),
        )
    except ConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return deleted
