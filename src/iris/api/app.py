from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pymongo
import uvicorn
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from iris import config_store
from iris.config import config_mapping, load_config
from iris.models import ServiceConfig

from .routes_admin import router as admin_router
from .routes_auth import router as auth_router
from .routes_cameras import router as cameras_router
from .routes_chat import router as chat_router
from .routes_dashboard import router as dashboard_router
from .routes_detections import router as detections_router


def _resolved_config_db_path(config_db_path: str | Path | None) -> Path:
    # Misma lógica que iris.__main__._resolved_config_db_path y
    # iris.users_cli._resolved_config_db_path, duplicada aquí a propósito:
    # es minúscula y evita acoplar el proceso de la API a esos módulos CLI.
    return (
        Path(config_db_path).expanduser()
        if config_db_path is not None
        else Path(os.environ.get("IRIS_CONFIG_DB", "data/config.db")).expanduser()
    )


def _require_auth_secret(config: ServiceConfig) -> None:
    if not config.auth_jwt_secret:
        raise RuntimeError(
            "Falta AUTH_JWT_SECRET: la API no puede iniciar sin un secreto para "
            "firmar los JWT de sesión. Genera uno con:\n"
            '  python -c "import secrets; print(secrets.token_urlsafe(32))"\n'
            "y agrégalo a tu .env o al almacén SQLite de configuración "
            "(AUTH_JWT_SECRET=...)."
        )


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        client = getattr(app.state, "mongo_client", None)
        if client is not None:
            client.close()


def create_app(
    *,
    config_db_path: str | Path | None = None,
    dotenv_path: str | Path | None = None,
) -> FastAPI:
    """Crea la aplicación FastAPI de IRIS (historial + administración).

    ``config_db_path``/``dotenv_path`` son opcionales y existen para que las
    pruebas puedan apuntar a un SQLite/​.env temporal sin depender de variables
    de entorno de proceso; en producción se llama sin argumentos y se resuelve
    igual que ``iris-monitor`` (``IRIS_CONFIG_DB`` o ``data/config.db``, ``.env``
    en el directorio actual).
    """

    resolved_db_path = _resolved_config_db_path(config_db_path)
    config = load_config(dotenv_path=dotenv_path, config_db_path=config_db_path)
    _require_auth_secret(config)
    seed_values = config_mapping(config, include_secrets_and_infrastructure=False)
    # La clave de DashScope es editable desde el panel y debe sobrevivir a un
    # reinicio aunque el .env original ya no esté. SQLite se crea con permisos
    # 0600 y la API nunca devuelve el valor en sus respuestas.
    seed_values["DASHSCOPE_API_KEY"] = config.alibaba.api_key
    if config.openai_api_key:
        seed_values["OPENAI_API_KEY"] = config.openai_api_key
    config_store.initialize_config_mapping(resolved_db_path, seed_values)
    stored_mapping = config_store.read_config_mapping(resolved_db_path)
    if "DASHSCOPE_API_KEY" not in stored_mapping:
        config_store.mutate_config_mapping(
            resolved_db_path,
            values={"DASHSCOPE_API_KEY": config.alibaba.api_key},
        )
    if config.openai_api_key and "OPENAI_API_KEY" not in stored_mapping:
        config_store.mutate_config_mapping(
            resolved_db_path,
            values={"OPENAI_API_KEY": config.openai_api_key},
        )
    # Reload once after a possible first seed so app.state always reflects
    # the exact SQLite-backed control-plane snapshot.
    config = load_config(dotenv_path=dotenv_path, config_db_path=config_db_path)

    app = FastAPI(title="IRIS API", version="0.1.0", lifespan=_lifespan)
    app.state.config = config
    app.state.users_db_path = resolved_db_path

    @app.exception_handler(RequestValidationError)
    async def safe_validation_error(
        _request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        # FastAPI/Pydantic normally echoes the rejected input in a 422. That
        # is useful for public fields but unsafe for write-only API keys,
        # passwords and future secrets. Field location and message are enough
        # for the UI to explain the error.
        errors = [
            {key: value for key, value in error.items() if key not in {"ctx", "input", "url"}}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.api_cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if config.mongo_uri is not None:
        client: pymongo.MongoClient = pymongo.MongoClient(
            config.mongo_uri,
            serverSelectionTimeoutMS=5_000,
        )
        app.state.detections_collection = client[config.mongo_database][
            config.mongo_detection_collection
        ]
        app.state.mongo_client = client
    else:
        app.state.detections_collection = None
        app.state.mongo_client = None

    app.include_router(auth_router, prefix="/auth", tags=["auth"])
    app.include_router(detections_router, prefix="/detections", tags=["detections"])
    app.include_router(cameras_router, prefix="/cameras", tags=["cameras"])
    app.include_router(chat_router, prefix="/chat", tags=["chat"])
    app.include_router(admin_router, prefix="/admin", tags=["admin"])
    app.include_router(dashboard_router, prefix="/api", tags=["dashboard"])

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def run() -> None:
    """Punto de entrada de ``iris-api``: valida config y arranca uvicorn."""

    config = load_config()
    _require_auth_secret(config)
    uvicorn.run(
        "iris.api.app:create_app",
        factory=True,
        host=config.api_host,
        port=config.api_port,
    )


if __name__ == "__main__":
    run()
