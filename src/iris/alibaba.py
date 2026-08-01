from __future__ import annotations

import base64
import json
import math
import random
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx

from iris.models import AlibabaConfig, AnalysisResult, CameraConfig

_RETRYABLE_STATUS_CODES = {408, 409, 425, 429}
_MAX_INLINE_JPEG_BYTES = 7_000_000
_RISK_SEVERITY_THRESHOLDS = (
    (90, "critical"),
    (70, "high"),
    (50, "medium"),
    (30, "low"),
    (10, "info"),
    (0, "none"),
)
_CRITICALITY_COLORS = ("verde", "amarillo", "naranja", "rojo")


def _severity_bands_text() -> str:
    """Render `_RISK_SEVERITY_THRESHOLDS` as an ascending `min-max=severity` list.

    Single source of truth shared with the model prompt: the bands the model
    sees are always exactly the ones `_severity_from_risk_score` applies,
    they can never drift apart.
    """

    ascending = list(reversed(_RISK_SEVERITY_THRESHOLDS))
    bands = []
    for index, (minimum, severity) in enumerate(ascending):
        maximum = ascending[index + 1][0] - 1 if index + 1 < len(ascending) else 100
        bands.append(f"{minimum}-{maximum}={severity}")
    return ", ".join(bands)


_SEVERITY_BANDS_TEXT = _severity_bands_text()
_OUTPUT_CONTRACT = f"""
Contrato técnico obligatorio de IRIS (no editable):
Devuelve únicamente un objeto JSON con risk_score (entero 0..100), event
(string snake_case), confidence (número 0..1), summary (string), observations
(lista de strings), recommended_action (string), requires_human_review
(booleano) y criticidad (string). risk_score mide riesgo visible, no
incertidumbre. No decidas severity ni alert: IRIS los calcula de forma
determinista a partir de risk_score con estas bandas exactas ({_SEVERITY_BANDS_TEXT}):
úsalas sólo como referencia para calibrar tu risk_score de forma consistente,
nunca las devuelvas como campos propios. criticidad es tu propio juicio
independiente sobre qué tan crítica se ve la escena, expresado como uno de
estos cuatro colores exactos: "verde" (sin riesgo aparente), "amarillo"
(riesgo leve), "naranja" (riesgo moderado) o "rojo" (riesgo grave o
potencialmente mortal). criticidad es informativa: se muestra junto a la
severidad calculada por IRIS, pero nunca la reemplaza. summary debe ser una
descripción completa de la escena (2-3 oraciones, no un titular breve) que
mencione explícitamente tu propio risk_score al inicio, con el formato
"Riesgo X/100: ..." seguido del detalle de lo observado. observations debe
listar, en frases separadas, los detalles adicionales que respaldan esa
descripción (postura, ubicación, objetos relevantes, personas involucradas).
""".strip()


class AlibabaAPIError(RuntimeError):
    """Raised after an Alibaba Model Studio request fails."""


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()
    return ""


def _severity_from_risk_score(risk_score: int) -> str:
    for minimum, severity in _RISK_SEVERITY_THRESHOLDS:
        if risk_score >= minimum:
            return severity
    raise AssertionError("risk_score validado fuera del rango 0..100.")


def _json_from_text(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].strip().lower() in {"```", "```json"}:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise AlibabaAPIError("Alibaba no devolvió un objeto JSON válido.") from exc
    if not isinstance(parsed, dict):
        raise AlibabaAPIError("Alibaba devolvió JSON, pero no un objeto.")

    if parsed.get("event") is None:
        parsed["event"] = "none"

    required_strings = ("event", "summary", "recommended_action")
    risk_score = parsed.get("risk_score")
    if (
        isinstance(risk_score, bool)
        or not isinstance(risk_score, int)
        or not 0 <= risk_score <= 100
    ):
        raise AlibabaAPIError("El análisis no contiene risk_score como entero entre 0 y 100.")
    for field_name in required_strings:
        if not isinstance(parsed.get(field_name), str) or not parsed[field_name].strip():
            raise AlibabaAPIError(f"El análisis no contiene {field_name} válido.")
    confidence = parsed.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(float(confidence))
        or not 0 <= confidence <= 1
    ):
        raise AlibabaAPIError("El análisis contiene confidence fuera de 0..1.")
    observations = parsed.get("observations")
    if observations is None:
        observations = []
    elif isinstance(observations, str):
        observations = [observations]
    if isinstance(observations, list):
        observations = [
            item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
            for item in observations
        ]
    if not isinstance(observations, list) or not all(
        isinstance(item, str) for item in observations
    ):
        raise AlibabaAPIError("El análisis no contiene observations como lista de texto.")
    parsed["observations"] = observations
    if not isinstance(parsed.get("requires_human_review"), bool):
        raise AlibabaAPIError("El análisis no contiene requires_human_review como booleano.")
    criticidad = parsed.get("criticidad")
    if not isinstance(criticidad, str) or criticidad.strip().lower() not in _CRITICALITY_COLORS:
        raise AlibabaAPIError(
            "El análisis no contiene criticidad válida (verde, amarillo, naranja o rojo)."
        )
    parsed["criticidad"] = criticidad.strip().lower()
    parsed["severity"] = _severity_from_risk_score(risk_score)
    parsed["alert"] = risk_score >= 70
    return parsed


class AlibabaVisionClient:
    """HTTP adapter for Alibaba Model Studio's OpenAI-compatible API."""

    def __init__(
        self,
        config: AlibabaConfig,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        random_source: random.Random | None = None,
    ) -> None:
        self._config = config
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=config.timeout_seconds)
        self._sleep = sleep
        self._interruptible_sleep = sleep is time.sleep
        self._random = random_source or random.Random()
        self._cancel_event = threading.Event()

    def close(self) -> None:
        self.cancel()
        if self._owns_client:
            self._client.close()

    def cancel(self) -> None:
        self._cancel_event.set()

    def __enter__(self) -> AlibabaVisionClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def analyze(
        self,
        jpeg: bytes,
        *,
        camera: CameraConfig,
        captured_at: str,
    ) -> AnalysisResult:
        if len(jpeg) > _MAX_INLINE_JPEG_BYTES:
            raise AlibabaAPIError("La captura JPEG supera 7 MB; reduce la resolución o calidad.")
        image = base64.b64encode(jpeg).decode("ascii")
        technical_context = (
            f"{camera.prompt}\n\n"
            f"{_OUTPUT_CONTRACT}\n\n"
            "Contexto técnico de esta captura:\n"
            f"- cámara: {camera.name}\n"
            f"- fecha_hora_utc: {captured_at}\n\n"
            "risk_score debe ser un entero entre 0 y 100 que represente el riesgo "
            "visible. confidence debe permanecer entre 0 y 1 y es tu propio juicio de "
            "qué tan bien pudiste interpretar la escena, no el nivel de riesgo: baja "
            "si la imagen está ocluida, mal iluminada, borrosa, o si tus propias "
            "observations/summary son vagos o inciertos; alta si pudiste describir la "
            "escena con claridad y detalle.\n"
            "Esquema obligatorio: risk_score (entero), event (string snake_case), "
            "confidence (número), summary (string), observations (lista de strings), "
            "recommended_action (string), requires_human_review (booleano) y "
            "criticidad (string: exactamente \"verde\", \"amarillo\", \"naranja\" o "
            "\"rojo\", tu propio juicio de qué tan crítica se ve la escena). "
            "severity y alert son calculados por IRIS a partir de risk_score y no "
            "deben decidirse aquí; criticidad sí es tu propia lectura y se muestra "
            "por separado.\n\n"
            "Devuelve únicamente un objeto JSON."
        )
        payload = {
            "model": self._config.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image}",
                            },
                        },
                        {"type": "text", "text": technical_context},
                    ],
                },
            ],
            "response_format": {"type": "json_object"},
            "enable_thinking": False,
            "temperature": 0.1,
            "max_completion_tokens": self._config.max_completion_tokens,
        }
        response = self._request(payload)
        try:
            body = response.json()
            choice = body["choices"][0]
            text = _content_text(choice["message"]["content"])
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            request_id = response.headers.get("x-request-id", "unknown")
            raise AlibabaAPIError(
                f"Respuesta inválida de Alibaba (request_id={request_id})."
            ) from exc
        if not text:
            raise AlibabaAPIError("Alibaba devolvió contenido vacío.")
        finish_reason = choice.get("finish_reason")
        if finish_reason not in {None, "stop"}:
            raise AlibabaAPIError(
                f"Alibaba terminó la respuesta con finish_reason={finish_reason!r}."
            )

        usage = body.get("usage")
        return AnalysisResult(
            data=_json_from_text(text),
            raw_text=text,
            model=body.get("model", self._config.model),
            usage=usage if isinstance(usage, dict) else None,
            request_id=response.headers.get("x-request-id"),
        )

    def _request(self, payload: dict[str, Any]) -> httpx.Response:
        url = f"{self._config.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "iris-care-monitor/0.1",
        }
        last_error: Exception | None = None
        total_attempts = self._config.max_retries + 1
        for attempt in range(total_attempts):
            if self._cancel_event.is_set():
                raise AlibabaAPIError("El análisis fue cancelado durante el apagado.")
            try:
                response = self._client.post(url, headers=headers, json=payload)
                if response.is_success:
                    return response
                if (
                    response.status_code not in _RETRYABLE_STATUS_CODES
                    and response.status_code < 500
                ):
                    self._raise_http_error(response)
                last_error = AlibabaAPIError(f"Alibaba respondió HTTP {response.status_code}.")
                retry_after = _retry_after_seconds(response)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                retry_after = None

            if attempt + 1 >= total_attempts:
                break
            delay = (
                retry_after
                if retry_after is not None
                else min(2**attempt + self._random.uniform(0, 0.25), 15.0)
            )
            delay = min(delay, 30.0)
            if self._interruptible_sleep:
                if self._cancel_event.wait(delay):
                    raise AlibabaAPIError("El análisis fue cancelado durante el apagado.")
            else:
                self._sleep(delay)

        raise AlibabaAPIError(
            f"No fue posible completar la solicitud a Alibaba tras {total_attempts} intento(s)."
        ) from last_error

    @staticmethod
    def _raise_http_error(response: httpx.Response) -> None:
        request_id = response.headers.get("x-request-id", "unknown")
        try:
            body = response.json()
        except ValueError:
            detail = response.text[:400]
        else:
            if isinstance(body, dict):
                nested_error = body.get("error")
                nested_message = (
                    nested_error.get("message") if isinstance(nested_error, dict) else None
                )
                code = str(body.get("code", ""))[:80]
                message = str(body.get("message") or nested_message or "")[:400]
                detail = f"code={code!r}, message={message!r}"
            else:
                detail = "respuesta de error sin detalle estructurado"
        raise AlibabaAPIError(
            f"Alibaba respondió HTTP {response.status_code} (request_id={request_id}): {detail}"
        )


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
