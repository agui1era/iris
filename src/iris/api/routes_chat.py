from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from iris.chat_store import add_message, create_thread, get_thread, list_messages, list_threads
from iris.config import ConfigurationError, load_config
from iris.history_chat import (
    HistoryChatError,
    OpenAIHistoryClient,
    aggregate_detections,
    compact_conversation,
)

from .security import CurrentUser

router = APIRouter()


class ChatCamera(BaseModel):
    id: str
    name: str


class ChatConfigResponse(BaseModel):
    enabled: bool
    configured: bool
    model: str
    max_range_days: int
    cameras: list[ChatCamera]


class ChatQueryRequest(BaseModel):
    camera_id: str = Field(min_length=1, max_length=50)
    date_from: datetime
    date_to: datetime
    question: str = Field(min_length=2, max_length=2_000)
    language: Literal["es", "en"] = "es"
    thread_id: str | None = Field(default=None, max_length=64)

    @field_validator("date_from", "date_to")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("La fecha debe incluir zona horaria.")
        return value


class ChatQueryResponse(BaseModel):
    thread_id: str
    answer: str
    source_count: int
    group_count: int


class ThreadDetailResponse(BaseModel):
    thread: dict[str, Any]
    messages: list[dict[str, Any]]


def _fresh_config(request: Request):
    try:
        return load_config(config_db_path=request.app.state.users_db_path)
    except ConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/config", response_model=ChatConfigResponse)
def get_chat_config(request: Request, user: CurrentUser) -> ChatConfigResponse:
    config = _fresh_config(request)
    return ChatConfigResponse(
        enabled=config.history_chat_enabled,
        configured=bool(config.openai_api_key),
        model=config.history_chat_model,
        max_range_days=config.history_chat_max_range_days,
        cameras=[ChatCamera(id=camera.identifier, name=camera.name) for camera in config.cameras],
    )


@router.get("/threads")
def get_threads(request: Request, user: CurrentUser) -> list[dict[str, Any]]:
    threads = list_threads(request.app.state.users_db_path, user.username)
    return [asdict(thread) for thread in threads]


@router.get("/threads/{thread_id}", response_model=ThreadDetailResponse)
def get_thread_detail(
    thread_id: str,
    request: Request,
    user: CurrentUser,
) -> ThreadDetailResponse:
    thread = get_thread(request.app.state.users_db_path, thread_id, user.username)
    if thread is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada.")
    return ThreadDetailResponse(
        thread=asdict(thread),
        messages=[
            asdict(message)
            for message in list_messages(request.app.state.users_db_path, thread.id)
        ],
    )


@router.post("/query", response_model=ChatQueryResponse)
def query_history(
    body: ChatQueryRequest,
    request: Request,
    user: CurrentUser,
) -> ChatQueryResponse:
    config = _fresh_config(request)
    if not config.history_chat_enabled:
        raise HTTPException(status_code=503, detail="El chat histórico está deshabilitado.")
    if not config.openai_api_key:
        raise HTTPException(status_code=503, detail="Falta configurar la API key de OpenAI.")
    if body.date_to <= body.date_from:
        raise HTTPException(
            status_code=422,
            detail="La fecha final debe ser posterior a la inicial.",
        )
    range_seconds = (body.date_to - body.date_from).total_seconds()
    if range_seconds > config.history_chat_max_range_days * 86_400:
        raise HTTPException(
            status_code=422,
            detail=f"El rango máximo es de {config.history_chat_max_range_days} días.",
        )
    camera = next((item for item in config.cameras if item.identifier == body.camera_id), None)
    if camera is None:
        raise HTTPException(status_code=404, detail="Cámara no encontrada.")

    date_from = body.date_from.isoformat()
    date_to = body.date_to.isoformat()
    db_path = request.app.state.users_db_path
    if body.thread_id:
        thread = get_thread(db_path, body.thread_id, user.username)
        if thread is None:
            raise HTTPException(status_code=404, detail="Conversación no encontrada.")
        if (
            thread.camera_id != camera.identifier
            or thread.date_from != date_from
            or thread.date_to != date_to
        ):
            raise HTTPException(
                status_code=409,
                detail="La cámara o el rango cambiaron; inicia una conversación nueva.",
            )
    else:
        thread = create_thread(
            db_path,
            username=user.username,
            camera_id=camera.identifier,
            camera_name=camera.name,
            date_from=date_from,
            date_to=date_to,
        )

    collection = getattr(request.app.state, "detections_collection", None)
    if collection is None:
        raise HTTPException(status_code=503, detail="MongoDB no está configurado.")
    cursor = collection.find(
        {
            "event_type": "analysis.completed",
            "camera_id": camera.identifier,
            "captured_at": {"$gte": date_from, "$lte": date_to},
        }
    ).sort("captured_at", 1)
    aggregate = aggregate_detections(cursor)
    add_message(db_path, thread.id, "user", body.question.strip())
    older_summary, recent_messages = compact_conversation(list_messages(db_path, thread.id))
    client = OpenAIHistoryClient(config.openai_api_key, config.history_chat_model)
    try:
        answer = client.answer(
            camera_name=f"{camera.name} ({camera.identifier})",
            date_from=date_from,
            date_to=date_to,
            language=body.language,
            aggregate=aggregate,
            older_summary=older_summary,
            recent_messages=recent_messages,
        )
    except HistoryChatError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    finally:
        client.close()
    add_message(db_path, thread.id, "assistant", answer)
    return ChatQueryResponse(
        thread_id=thread.id,
        answer=answer,
        source_count=aggregate["total_detections"],
        group_count=aggregate["distinct_event_groups"],
    )
