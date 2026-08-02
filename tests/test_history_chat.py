from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from iris.chat_store import ChatMessage
from iris.history_chat import aggregate_detections, compact_conversation
from iris.users_store import create_user


def test_aggregate_detections_consumes_all_repetitions() -> None:
    documents = [
        {
            "captured_at": f"2026-08-02T10:{index:02d}:00+00:00",
            "analysis": {
                "event": "no_event" if index < 40 else "caida",
                "severity": "none" if index < 40 else "high",
                "risk_score": 0 if index < 40 else 80,
                "summary": "Sin novedades" if index < 40 else "Persona en el suelo",
            },
        }
        for index in range(60)
    ]

    result = aggregate_detections(iter(documents))

    assert result["total_detections"] == 60
    assert result["distinct_event_groups"] == 2
    assert {group["count"] for group in result["groups"]} == {20, 40}


def test_compact_conversation_keeps_exactly_twenty_full_messages() -> None:
    messages = [
        ChatMessage(
            id=index,
            thread_id="thread",
            role="user" if index % 2 else "assistant",
            content=f"mensaje {index}",
            created_at="2026-08-02T00:00:00+00:00",
        )
        for index in range(1, 26)
    ]

    summary, recent = compact_conversation(messages)

    assert "5 mensajes anteriores" in summary
    assert len(recent) == 20
    assert recent[0]["content"] == "mensaje 6"
    assert recent[-1]["content"] == "mensaje 25"


class FakeCursor(list[dict[str, Any]]):
    def sort(self, field: str, direction: int) -> FakeCursor:
        super().sort(key=lambda item: item.get(field, ""), reverse=direction < 0)
        return self


class FakeCollection:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.queries: list[dict[str, Any]] = []

    def find(self, query: dict[str, Any]) -> FakeCursor:
        self.queries.append(query)
        return FakeCursor(self.documents)


class FakeOpenAIHistoryClient:
    calls: list[dict[str, Any]] = []

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def answer(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return "Hubo una caída de riesgo alto a las 10:05."

    def close(self) -> None:
        return None


def test_normal_user_can_query_one_camera_range(
    api_app_factory,
    monkeypatch,
) -> None:
    from iris.api import routes_chat

    app, users_db, _ = api_app_factory(
        OPENAI_API_KEY="test-openai-key",
        MONGO_URI="mongodb://localhost:27017",
    )
    app.state.detections_collection = FakeCollection(
        [
            {
                "event_type": "analysis.completed",
                "camera_id": "CAM1",
                "captured_at": "2026-08-02T10:00:00+00:00",
                "analysis": {
                    "event": "caida",
                    "severity": "high",
                    "risk_score": 80,
                    "summary": "Persona en el suelo",
                },
            },
            {
                "event_type": "analysis.completed",
                "camera_id": "CAM1",
                "captured_at": "2026-08-02T10:05:00+00:00",
                "analysis": {
                    "event": "caida",
                    "severity": "high",
                    "risk_score": 85,
                    "summary": "Persona continúa en el suelo",
                },
            },
        ]
    )
    monkeypatch.setattr(routes_chat, "OpenAIHistoryClient", FakeOpenAIHistoryClient)
    create_user(users_db, "analista", "s3cr3t", "normal")
    client = TestClient(app)
    token = client.post(
        "/auth/login",
        json={"username": "analista", "password": "s3cr3t"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/chat/query",
        headers=headers,
        json={
            "camera_id": "CAM1",
            "date_from": "2026-08-02T09:00:00-04:00",
            "date_to": "2026-08-02T11:00:00-04:00",
            "question": "¿Qué pasó?",
            "language": "es",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_count"] == 2
    assert body["group_count"] == 1
    assert body["answer"].startswith("Hubo una caída")
    detail = client.get(f"/chat/threads/{body['thread_id']}", headers=headers)
    assert [message["role"] for message in detail.json()["messages"]] == [
        "user",
        "assistant",
    ]
    assert FakeOpenAIHistoryClient.calls[-1]["recent_messages"][-1]["content"] == "¿Qué pasó?"
