from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from iris.alibaba import AlibabaAPIError, AlibabaVisionClient, _json_from_text
from iris.models import AlibabaConfig, CameraConfig


class FakeHTTPClient:
    def __init__(self, outcomes: list[httpx.Response | Exception]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> httpx.Response:
        self.calls.append({"url": url, "headers": headers, "json": json})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def close(self) -> None:
        self.closed = True


class ZeroJitter:
    @staticmethod
    def uniform(start: float, end: float) -> float:
        assert (start, end) == (0, 0.25)
        return 0.0


def make_alibaba_config(*, max_retries: int = 3) -> AlibabaConfig:
    return AlibabaConfig(
        api_key="secret-api-key",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        model="qwen-test",
        timeout_seconds=7.0,
        max_retries=max_retries,
        max_completion_tokens=321,
    )


def make_camera() -> CameraConfig:
    return CameraConfig(
        index=2,
        name="Dormitorio",
        rtsp_url="rtsp://camera-two/live",
        prompt="Detecta caídas y pide revisión humana ante dudas.",
    )


def care_analysis(**overrides: Any) -> dict[str, Any]:
    analysis: dict[str, Any] = {
        "alert": False,
        "severity": "none",
        "risk_score": 0,
        "event": "normal",
        "confidence": 0.98,
        "summary": "Sin novedad",
        "observations": [],
        "recommended_action": "Ninguna",
        "requires_human_review": False,
        "criticidad": "verde",
    }
    analysis.update(overrides)
    return analysis


def successful_response() -> httpx.Response:
    model_analysis = care_analysis(
        alert=True,
        severity="critical",
        risk_score=9,
        criticidad="rojo",
    )
    return httpx.Response(
        200,
        headers={"x-request-id": "request-ok"},
        json={
            "model": "qwen-response",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "choices": [
                {
                    "message": {
                        "content": (
                            f"```json\n{json.dumps(model_analysis, ensure_ascii=False)}\n```"
                        )
                    }
                }
            ],
        },
    )


def test_analyze_builds_openai_compatible_multimodal_payload_and_parses_result() -> None:
    fake_http = FakeHTTPClient([successful_response()])
    client = AlibabaVisionClient(make_alibaba_config(), client=fake_http)
    jpeg = b"\xff\xd8fake-jpeg\xff\xd9"

    result = client.analyze(
        jpeg,
        camera=make_camera(),
        captured_at="2026-07-27T12:34:56+00:00",
    )

    assert result.data == {
        "alert": False,
        "severity": "none",
        "risk_score": 9,
        "event": "normal",
        "confidence": 0.98,
        "summary": "Sin novedad",
        "observations": [],
        "recommended_action": "Ninguna",
        "requires_human_review": False,
        "criticidad": "rojo",
    }
    assert result.model == "qwen-response"
    assert result.usage == {"prompt_tokens": 10, "completion_tokens": 5}
    assert len(fake_http.calls) == 1
    request = fake_http.calls[0]
    assert request["url"] == (
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"
    )
    assert request["headers"]["Authorization"] == "Bearer secret-api-key"
    payload = request["json"]
    assert payload["model"] == "qwen-test"
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["enable_thinking"] is False
    assert payload["max_completion_tokens"] == 321
    assert len(payload["messages"]) == 1
    user_message = payload["messages"][0]
    assert user_message["role"] == "user"
    assert all(message["role"] != "system" for message in payload["messages"])
    image_url = user_message["content"][0]["image_url"]["url"]
    assert image_url.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(image_url.removeprefix("data:image/jpeg;base64,")) == jpeg
    technical_text = user_message["content"][1]["text"]
    assert "Detecta caídas" in technical_text
    assert "Contrato técnico obligatorio de IRIS" in technical_text
    assert "risk_score (entero 0..100)" in technical_text
    assert "cámara: Dormitorio" in technical_text
    assert "fecha_hora_utc: 2026-07-27T12:34:56+00:00" in technical_text
    assert "risk_score debe ser un entero entre 0 y 100" in technical_text
    assert "confidence debe permanecer entre 0 y 1" in technical_text
    assert "qué tan bien pudiste interpretar la escena" in technical_text
    assert "observations/summary son vagos o inciertos" in technical_text
    assert "variacion" not in technical_text.lower()
    assert "criticidad" in technical_text
    assert '"verde"' in technical_text
    assert '"amarillo"' in technical_text
    assert '"naranja"' in technical_text
    assert '"rojo"' in technical_text
    assert "0-9=none, 10-29=info, 30-49=low, 50-69=medium, 70-89=high, 90-100=critical" in (
        technical_text
    )
    assert "Riesgo X/100" in technical_text
    assert "2-3 oraciones" in technical_text


@pytest.mark.parametrize(
    ("risk_score", "expected_severity", "expected_alert"),
    [
        (0, "none", False),
        (9, "none", False),
        (10, "info", False),
        (29, "info", False),
        (30, "low", False),
        (49, "low", False),
        (50, "medium", False),
        (69, "medium", False),
        (70, "high", True),
        (89, "high", True),
        (90, "critical", True),
        (100, "critical", True),
    ],
)
def test_risk_score_boundaries_normalize_severity_and_alert_server_side(
    risk_score: int,
    expected_severity: str,
    expected_alert: bool,
) -> None:
    model_analysis = care_analysis(
        risk_score=risk_score,
        severity={"untrusted": "value"},
        alert="untrusted",
    )

    parsed = _json_from_text(json.dumps(model_analysis))

    assert parsed["risk_score"] == risk_score
    assert parsed["severity"] == expected_severity
    assert parsed["alert"] is expected_alert


def test_alert_and_severity_do_not_need_to_be_supplied_by_the_model() -> None:
    model_analysis = care_analysis(risk_score=95)
    model_analysis.pop("alert")
    model_analysis.pop("severity")

    parsed = _json_from_text(json.dumps(model_analysis))

    assert parsed["severity"] == "critical"
    assert parsed["alert"] is True


@pytest.mark.parametrize(
    "invalid_risk_score",
    [None, True, False, -1, 101, 70.0, "70"],
)
def test_rejects_risk_score_that_is_not_an_integer_between_zero_and_one_hundred(
    invalid_risk_score: Any,
) -> None:
    model_analysis = care_analysis(risk_score=invalid_risk_score)

    with pytest.raises(AlibabaAPIError, match="risk_score.*entero entre 0 y 100"):
        _json_from_text(json.dumps(model_analysis))


def test_confidence_is_preserved_and_not_used_as_the_risk_score() -> None:
    model_analysis = care_analysis(
        risk_score=100,
        confidence=0.01,
        severity="none",
        alert=False,
    )

    parsed = _json_from_text(json.dumps(model_analysis))

    assert parsed["confidence"] == pytest.approx(0.01)
    assert parsed["risk_score"] == 100
    assert parsed["severity"] == "critical"
    assert parsed["alert"] is True


@pytest.mark.parametrize("invalid_confidence", [True, -0.01, 1.01, float("nan"), "0.5"])
def test_confidence_still_must_be_a_number_between_zero_and_one(
    invalid_confidence: Any,
) -> None:
    model_analysis = care_analysis(risk_score=70, confidence=invalid_confidence)

    with pytest.raises(AlibabaAPIError, match="confidence fuera de 0..1"):
        _json_from_text(json.dumps(model_analysis))


@pytest.mark.parametrize(
    "invalid_criticidad",
    [None, "", "  ", "azul", "critico", 1, True, ["rojo"]],
)
def test_rejects_criticidad_outside_the_four_allowed_colors(invalid_criticidad: Any) -> None:
    model_analysis = care_analysis(criticidad=invalid_criticidad)

    with pytest.raises(AlibabaAPIError, match="criticidad"):
        _json_from_text(json.dumps(model_analysis))


def test_criticidad_missing_entirely_is_rejected() -> None:
    model_analysis = care_analysis()
    model_analysis.pop("criticidad")

    with pytest.raises(AlibabaAPIError, match="criticidad"):
        _json_from_text(json.dumps(model_analysis))


@pytest.mark.parametrize(
    ("raw_criticidad", "expected"),
    [
        ("verde", "verde"),
        ("VERDE", "verde"),
        (" Amarillo ", "amarillo"),
        ("NARANJA", "naranja"),
        ("Rojo", "rojo"),
    ],
)
def test_criticidad_is_normalized_to_lowercase(raw_criticidad: str, expected: str) -> None:
    model_analysis = care_analysis(criticidad=raw_criticidad)

    parsed = _json_from_text(json.dumps(model_analysis))

    assert parsed["criticidad"] == expected


def test_retries_retryable_responses_using_retry_after_then_exponential_backoff() -> None:
    fake_http = FakeHTTPClient(
        [
            httpx.Response(429, headers={"retry-after": "1.25"}),
            httpx.Response(503),
            successful_response(),
        ]
    )
    sleeps: list[float] = []
    client = AlibabaVisionClient(
        make_alibaba_config(max_retries=2),
        client=fake_http,
        sleep=sleeps.append,
        random_source=ZeroJitter(),
    )

    response = client._request({"test": True})

    assert response.status_code == 200
    assert len(fake_http.calls) == 3
    assert sleeps == [1.25, 2.0]


def test_retries_transport_error_and_then_succeeds() -> None:
    fake_http = FakeHTTPClient(
        [
            httpx.ReadTimeout("camera analysis timed out"),
            successful_response(),
        ]
    )
    sleeps: list[float] = []
    client = AlibabaVisionClient(
        make_alibaba_config(max_retries=1),
        client=fake_http,
        sleep=sleeps.append,
        random_source=ZeroJitter(),
    )

    response = client._request({"test": True})

    assert response.status_code == 200
    assert len(fake_http.calls) == 2
    assert sleeps == [1.0]


def test_does_not_retry_unauthorized_response() -> None:
    fake_http = FakeHTTPClient(
        [
            httpx.Response(
                401,
                headers={"x-request-id": "request-denied"},
                json={"message": "invalid api key"},
            )
        ]
    )
    sleeps: list[float] = []
    client = AlibabaVisionClient(
        make_alibaba_config(max_retries=5),
        client=fake_http,
        sleep=sleeps.append,
        random_source=ZeroJitter(),
    )

    with pytest.raises(AlibabaAPIError) as error:
        client._request({"test": True})

    assert len(fake_http.calls) == 1
    assert sleeps == []
    assert "HTTP 401" in str(error.value)
    assert "request-denied" in str(error.value)


@pytest.mark.parametrize(
    "body_factory",
    [
        lambda: {"choices": []},
        lambda: {"choices": [{"message": {"content": ""}}]},
    ],
)
def test_analyze_rejects_structurally_invalid_or_empty_api_response(
    body_factory: Callable[[], dict[str, Any]],
) -> None:
    fake_http = FakeHTTPClient([httpx.Response(200, json=body_factory())])
    client = AlibabaVisionClient(make_alibaba_config(), client=fake_http)

    with pytest.raises(AlibabaAPIError):
        client.analyze(
            b"jpeg",
            camera=make_camera(),
            captured_at="2026-07-27T12:34:56+00:00",
        )


def test_analyze_normalizes_null_event_to_none() -> None:
    fake_http = FakeHTTPClient(
        [
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": (
                                    '{"alert":false,"severity":"none","risk_score":0,'
                                    '"event":null,'
                                    '"confidence":0.98,"summary":"Sin novedad",'
                                    '"observations":[],"recommended_action":"Ninguna",'
                                    '"requires_human_review":false,"criticidad":"verde"}'
                                )
                            },
                        }
                    ]
                },
            )
        ]
    )
    client = AlibabaVisionClient(make_alibaba_config(), client=fake_http)

    result = client.analyze(
        b"jpeg",
        camera=make_camera(),
        captured_at="2026-07-27T12:34:56+00:00",
    )

    assert result.data["event"] == "none"


@pytest.mark.parametrize(
    ("raw_observations", "expected"),
    [
        ("null", []),
        ('"Persona sentada en una silla."', ["Persona sentada en una silla."]),
        ("[1, true, null]", ["1", "true", "null"]),
    ],
)
def test_analyze_normalizes_non_list_or_mixed_observations(
    raw_observations: str,
    expected: list[str],
) -> None:
    fake_http = FakeHTTPClient(
        [
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": (
                                    '{"alert":false,"severity":"none","risk_score":0,'
                                    '"event":"none",'
                                    '"confidence":0.98,"summary":"Sin novedad",'
                                    f'"observations":{raw_observations},'
                                    '"recommended_action":"Ninguna",'
                                    '"requires_human_review":false,"criticidad":"verde"}'
                                )
                            },
                        }
                    ]
                },
            )
        ]
    )
    client = AlibabaVisionClient(make_alibaba_config(), client=fake_http)

    result = client.analyze(
        b"jpeg",
        camera=make_camera(),
        captured_at="2026-07-27T12:34:56+00:00",
    )

    assert result.data["observations"] == expected


def test_analyze_rejects_json_that_does_not_match_care_schema() -> None:
    fake_http = FakeHTTPClient(
        [
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": '{"alert": false}'},
                        }
                    ]
                },
            )
        ]
    )
    client = AlibabaVisionClient(make_alibaba_config(), client=fake_http)

    with pytest.raises(AlibabaAPIError, match="risk_score"):
        client.analyze(
            b"jpeg",
            camera=make_camera(),
            captured_at="2026-07-27T12:34:56+00:00",
        )
