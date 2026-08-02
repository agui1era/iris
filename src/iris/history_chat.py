from __future__ import annotations

import json
import re
from typing import Any

import httpx

from iris.chat_store import ChatMessage

_NO_EVENT_ALIASES = {
    "",
    "none",
    "no event",
    "no event detected",
    "sin evento",
    "ningun evento",
    "ningún evento",
}
_MAX_EVENT_GROUPS = 120


class HistoryChatError(RuntimeError):
    pass


def _clean_text(value: object, *, limit: int = 300) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _event_name(analysis: dict[str, Any]) -> str:
    value = _clean_text(analysis.get("event"), limit=120)
    normalized = value.casefold().replace("_", " ").strip()
    if normalized in _NO_EVENT_ALIASES or (not value and analysis.get("alert") is False):
        return "sin_evento"
    return value or "evento_no_clasificado"


def aggregate_detections(documents: Any) -> dict[str, Any]:
    """Consume every matching detection while keeping the model payload bounded."""

    groups: dict[tuple[str, str], dict[str, Any]] = {}
    total = 0
    for document in documents:
        total += 1
        analysis = document.get("analysis")
        analysis = analysis if isinstance(analysis, dict) else {}
        event = _event_name(analysis)
        severity = _clean_text(analysis.get("severity"), limit=30) or "desconocida"
        key = (event.casefold(), severity.casefold())
        captured_at = _clean_text(document.get("captured_at"), limit=50)
        risk = analysis.get("risk_score")
        risk = risk if isinstance(risk, int) and not isinstance(risk, bool) else None
        summary = _clean_text(analysis.get("summary"))
        action = _clean_text(analysis.get("recommended_action"))
        group = groups.get(key)
        if group is None:
            group = {
                "event": event,
                "severity": severity,
                "count": 0,
                "first_at": captured_at,
                "last_at": captured_at,
                "max_risk": risk,
                "examples": [],
                "recommended_actions": [],
            }
            groups[key] = group
        group["count"] += 1
        if captured_at:
            group["last_at"] = captured_at
        if risk is not None and (group["max_risk"] is None or risk > group["max_risk"]):
            group["max_risk"] = risk
        if summary and summary not in group["examples"]:
            if len(group["examples"]) < 3:
                group["examples"].append(summary)
            elif group["examples"][-1] != summary:
                group["examples"][-1] = summary
        if (
            action
            and action not in group["recommended_actions"]
            and len(group["recommended_actions"]) < 3
        ):
            group["recommended_actions"].append(action)

    ordered_all = sorted(
        groups.values(),
        key=lambda item: ((item["max_risk"] or -1), item["count"]),
        reverse=True,
    )
    ordered = ordered_all[:_MAX_EVENT_GROUPS]
    omitted = ordered_all[_MAX_EVENT_GROUPS:]
    return {
        "total_detections": total,
        "distinct_event_groups": len(ordered_all),
        "included_event_groups": len(ordered),
        "omitted_event_groups": len(omitted),
        "omitted_detection_count": sum(group["count"] for group in omitted),
        "omitted_max_risk": max(
            (group["max_risk"] for group in omitted if group["max_risk"] is not None),
            default=None,
        ),
        "groups": ordered,
    }


def compact_conversation(messages: list[ChatMessage]) -> tuple[str, list[dict[str, str]]]:
    """Keep 20 full chat messages and compact anything older."""

    older = messages[:-20]
    recent = messages[-20:]
    if older:
        samples = older[-12:]
        lines = [
            f"- {message.role}: {_clean_text(message.content, limit=180)}"
            for message in samples
        ]
        summary = (
            f"Resumen compacto de {len(older)} mensajes anteriores "
            f"(se muestran los {len(samples)} más recientes):\n" + "\n".join(lines)
        )
    else:
        summary = "Sin mensajes anteriores fuera de la ventana reciente."
    return summary, [{"role": message.role, "content": message.content} for message in recent]


class OpenAIHistoryClient:
    def __init__(self, api_key: str, model: str, *, timeout_seconds: float = 60.0) -> None:
        self._api_key = api_key
        self._model = model
        self._client = httpx.Client(timeout=timeout_seconds)

    def answer(
        self,
        *,
        camera_name: str,
        date_from: str,
        date_to: str,
        language: str,
        aggregate: dict[str, Any],
        older_summary: str,
        recent_messages: list[dict[str, str]],
    ) -> str:
        language_name = "español" if language == "es" else "English"
        instructions = (
            "Eres el asistente de análisis histórico de IRIS. Responde únicamente usando "
            "los datos agregados entregados. Distingue hechos de inferencias, no inventes "
            "eventos y di claramente cuando el rango no contiene evidencia suficiente. "
            f"Responde en {language_name}. Los conteos representan detecciones, no personas "
            "ni incidentes necesariamente únicos. Sé conciso y útil."
        )
        payload = {
            "camera": camera_name,
            "date_from": date_from,
            "date_to": date_to,
            "detection_aggregation": aggregate,
            "older_chat_summary": older_summary,
            "recent_chat_messages": recent_messages,
        }
        try:
            response = self._client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "instructions": instructions,
                    "input": json.dumps(payload, ensure_ascii=False),
                    "max_output_tokens": 900,
                    "store": False,
                },
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HistoryChatError(
                "No se pudo obtener una respuesta del asistente histórico."
            ) from exc

        chunks: list[str] = []
        for item in body.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    chunks.append(content["text"])
        answer = "\n".join(chunks).strip()
        if not answer:
            raise HistoryChatError("El asistente histórico devolvió una respuesta vacía.")
        return answer

    def close(self) -> None:
        self._client.close()
