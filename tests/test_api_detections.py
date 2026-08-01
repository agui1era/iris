from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bson import ObjectId
from fastapi.testclient import TestClient

from iris.api.routes_detections import get_detections_collection
from iris.users_store import create_user

AUTH_HEADER_USERNAME = "viewer"


class FakeCursor:
    """Minimal stand-in for a pymongo Cursor: sort/skip/limit + iteration.

    Mirrors the codebase's existing convention of hand-written fakes for
    external systems (see ``MemoryEventSink`` in tests/test_service.py)
    instead of pulling in a mongomock dependency.
    """

    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self._documents = list(documents)

    def sort(self, field: str, direction: int) -> FakeCursor:
        # Mirrors real MongoDB dotted-path sort (e.g. "analysis.criticidad") and
        # tolerates documents missing the field instead of raising on mixed types.
        self._documents.sort(
            key=lambda doc: (_get_dotted(doc, field) is None, _get_dotted(doc, field)),
            reverse=direction < 0,
        )
        return self

    def skip(self, count: int) -> FakeCursor:
        self._documents = self._documents[count:]
        return self

    def limit(self, count: int) -> FakeCursor:
        self._documents = self._documents[:count]
        return self

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self._documents)


def _get_dotted(document: dict[str, Any], dotted_key: str) -> Any:
    value: Any = document
    for part in dotted_key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _matches(document: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        actual = _get_dotted(document, key)
        if isinstance(expected, dict):
            if "$gte" in expected and not (actual is not None and actual >= expected["$gte"]):
                return False
            if "$lte" in expected and not (actual is not None and actual <= expected["$lte"]):
                return False
        elif actual != expected:
            return False
    return True


class _FakeDeleteResult:
    def __init__(self, deleted_count: int) -> None:
        self.deleted_count = deleted_count


class FakeDetectionsCollection:
    """Hand-written pymongo-compatible fake over an in-memory document list."""

    def __init__(self, documents: Iterable[dict[str, Any]]) -> None:
        self._documents = list(documents)

    def find(self, query: dict[str, Any] | None = None) -> FakeCursor:
        query = query or {}
        return FakeCursor([doc for doc in self._documents if _matches(doc, query)])

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for document in self._documents:
            if _matches(document, query):
                return document
        return None

    def count_documents(self, query: dict[str, Any]) -> int:
        return sum(1 for doc in self._documents if _matches(doc, query))

    def delete_one(self, query: dict[str, Any]) -> _FakeDeleteResult:
        for index, document in enumerate(self._documents):
            if _matches(document, query):
                del self._documents[index]
                return _FakeDeleteResult(deleted_count=1)
        return _FakeDeleteResult(deleted_count=0)


def _make_document(
    *,
    object_id: ObjectId | None = None,
    camera_id: str = "CAM1",
    captured_at: str,
    severity: str = "high",
    criticidad: str = "rojo",
    snapshot_path: str | None = None,
) -> dict[str, Any]:
    return {
        "_id": object_id or ObjectId(),
        "event_type": "analysis.completed",
        "camera_id": camera_id,
        "camera_name": "Dormitorio",
        "captured_at": captured_at,
        "completed_at": captured_at,
        "trigger": "poll",
        "snapshot_path": snapshot_path,
        "analysis": {
            "risk_score": 75,
            "severity": severity,
            "alert": True,
            "event": "possible_fall",
            "summary": "Persona visible en el suelo.",
            "confidence": 0.9,
            "recommended_action": "Solicitar revisión.",
            "criticidad": criticidad,
        },
    }


def _authed_client(
    api_app_factory: Callable, documents: list[dict[str, Any]]
) -> tuple[TestClient, str, Path]:
    app, users_db, capture_dir = api_app_factory()
    create_user(users_db, AUTH_HEADER_USERNAME, "s3cr3t", "normal")
    # One shared instance across requests, like a real Mongo collection handle,
    # so mutations (e.g. delete_one) made in one request are visible in the next.
    collection = FakeDetectionsCollection(documents)
    app.dependency_overrides[get_detections_collection] = lambda: collection
    client = TestClient(app)
    login = client.post(
        "/auth/login", json={"username": AUTH_HEADER_USERNAME, "password": "s3cr3t"}
    )
    token = login.json()["access_token"]
    return client, token, capture_dir


def _admin_authed_client(
    api_app_factory: Callable, documents: list[dict[str, Any]]
) -> tuple[TestClient, str, Path]:
    app, users_db, capture_dir = api_app_factory()
    create_user(users_db, "admin-user", "s3cr3t", "admin")
    collection = FakeDetectionsCollection(documents)
    app.dependency_overrides[get_detections_collection] = lambda: collection
    client = TestClient(app)
    login = client.post("/auth/login", json={"username": "admin-user", "password": "s3cr3t"})
    token = login.json()["access_token"]
    return client, token, capture_dir


def test_latest_detections_returns_documents_sorted_by_captured_at_desc(
    api_app_factory: Callable,
) -> None:
    documents = [
        _make_document(captured_at="2026-07-20T10:00:00+00:00"),
        _make_document(captured_at="2026-07-25T10:00:00+00:00"),
        _make_document(captured_at="2026-07-22T10:00:00+00:00"),
    ]
    client, token, _ = _authed_client(api_app_factory, documents)

    response = client.get(
        "/detections/latest?limit=2", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["captured_at"] == "2026-07-25T10:00:00+00:00"
    assert body[1]["captured_at"] == "2026-07-22T10:00:00+00:00"
    assert body[0]["severity"] == "high"
    assert body[0]["risk_score"] == 75
    assert body[0]["has_image"] is False


def test_latest_detections_limit_is_capped(api_app_factory: Callable) -> None:
    documents = [
        _make_document(captured_at=f"2026-07-{day:02d}T10:00:00+00:00") for day in range(1, 10)
    ]
    client, token, _ = _authed_client(api_app_factory, documents)

    response = client.get(
        "/detections/latest?limit=100000", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert len(response.json()) == len(documents)


def test_detection_lists_exclude_connectivity_and_failed_events(
    api_app_factory: Callable,
) -> None:
    completed = _make_document(captured_at="2026-07-20T10:00:00+00:00")
    documents = [
        completed,
        {
            "_id": ObjectId(),
            "event_type": "camera.offline",
            "camera_id": "CAM1",
            "captured_at": "2026-07-22T10:00:00+00:00",
        },
        {
            "_id": ObjectId(),
            "event_type": "analysis.failed",
            "camera_id": "CAM1",
            "captured_at": "2026-07-21T10:00:00+00:00",
        },
    ]
    client, token, _ = _authed_client(api_app_factory, documents)
    headers = {"Authorization": f"Bearer {token}"}

    latest = client.get("/detections/latest", headers=headers)
    page = client.get("/detections", headers=headers)

    assert [item["id"] for item in latest.json()] == [str(completed["_id"])]
    assert [item["id"] for item in page.json()["items"]] == [str(completed["_id"])]


def test_latest_detections_without_token_is_rejected(api_app_factory: Callable) -> None:
    client, _, _ = _authed_client(api_app_factory, [])

    response = client.get("/detections/latest")

    assert response.status_code == 401


def test_list_detections_paginates_and_reports_total(api_app_factory: Callable) -> None:
    documents = [
        _make_document(captured_at=f"2026-07-{day:02d}T10:00:00+00:00") for day in range(1, 6)
    ]
    client, token, _ = _authed_client(api_app_factory, documents)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/detections?page=1&page_size=2", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert len(body["items"]) == 2
    # Most recent first.
    assert body["items"][0]["captured_at"] == "2026-07-05T10:00:00+00:00"

    second_page = client.get("/detections?page=2&page_size=2", headers=headers).json()
    assert [item["captured_at"] for item in second_page["items"]] == [
        "2026-07-03T10:00:00+00:00",
        "2026-07-02T10:00:00+00:00",
    ]


def test_list_detections_filters_by_camera_id_and_severity(api_app_factory: Callable) -> None:
    documents = [
        _make_document(camera_id="CAM1", severity="high", captured_at="2026-07-01T10:00:00+00:00"),
        _make_document(camera_id="CAM2", severity="high", captured_at="2026-07-02T10:00:00+00:00"),
        _make_document(camera_id="CAM1", severity="low", captured_at="2026-07-03T10:00:00+00:00"),
    ]
    client, token, _ = _authed_client(api_app_factory, documents)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/detections?camera_id=CAM1&severity=high", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["camera_id"] == "CAM1"
    assert body["items"][0]["severity"] == "high"


def test_list_detections_filters_by_date_range(api_app_factory: Callable) -> None:
    documents = [
        _make_document(captured_at="2026-07-01T10:00:00+00:00"),
        _make_document(captured_at="2026-07-10T10:00:00+00:00"),
        _make_document(captured_at="2026-07-20T10:00:00+00:00"),
    ]
    client, token, _ = _authed_client(api_app_factory, documents)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get(
        "/detections?date_from=2026-07-05T00:00:00+00:00&date_to=2026-07-15T00:00:00+00:00",
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["captured_at"] == "2026-07-10T10:00:00+00:00"


def test_list_detections_page_size_is_capped(api_app_factory: Callable) -> None:
    documents = [
        _make_document(captured_at=f"2026-07-{day:02d}T10:00:00+00:00") for day in range(1, 6)
    ]
    client, token, _ = _authed_client(api_app_factory, documents)

    response = client.get(
        "/detections?page_size=100000", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["page_size"] <= 200
    assert len(body["items"]) == 5


def test_detection_image_happy_path_returns_the_jpeg_bytes(
    api_app_factory: Callable,
) -> None:
    object_id = ObjectId()
    client, token, capture_dir = _authed_client(api_app_factory, [])
    camera_dir = capture_dir / "CAM1"
    camera_dir.mkdir(parents=True, exist_ok=True)
    image_path = camera_dir / "frame.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xd9fake-jpeg-bytes")

    documents = [
        _make_document(
            object_id=object_id,
            captured_at=datetime.now(UTC).isoformat(),
            snapshot_path=str(image_path),
        )
    ]
    client.app.dependency_overrides[get_detections_collection] = lambda: FakeDetectionsCollection(
        documents
    )

    response = client.get(
        f"/detections/{object_id}/image", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == b"\xff\xd8\xff\xd9fake-jpeg-bytes"


def test_detection_image_rejects_path_traversal_outside_capture_dir(
    api_app_factory: Callable,
) -> None:
    object_id = ObjectId()
    client, token, capture_dir = _authed_client(api_app_factory, [])
    outside_file = capture_dir.parent / "outside.jpg"
    outside_file.write_bytes(b"not-inside-capture-dir")

    documents = [
        _make_document(
            object_id=object_id,
            captured_at=datetime.now(UTC).isoformat(),
            snapshot_path=str(outside_file),
        )
    ]
    client.app.dependency_overrides[get_detections_collection] = lambda: FakeDetectionsCollection(
        documents
    )

    response = client.get(
        f"/detections/{object_id}/image", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 404


def test_detection_image_missing_file_returns_404(api_app_factory: Callable) -> None:
    object_id = ObjectId()
    client, token, capture_dir = _authed_client(api_app_factory, [])
    documents = [
        _make_document(
            object_id=object_id,
            captured_at=datetime.now(UTC).isoformat(),
            snapshot_path=str(capture_dir / "CAM1" / "does-not-exist.jpg"),
        )
    ]
    client.app.dependency_overrides[get_detections_collection] = lambda: FakeDetectionsCollection(
        documents
    )

    response = client.get(
        f"/detections/{object_id}/image", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 404


def test_detection_image_without_snapshot_returns_404(api_app_factory: Callable) -> None:
    object_id = ObjectId()
    documents = [
        _make_document(
            object_id=object_id,
            captured_at=datetime.now(UTC).isoformat(),
            snapshot_path=None,
        )
    ]
    client, token, _ = _authed_client(api_app_factory, documents)

    response = client.get(
        f"/detections/{object_id}/image", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 404


def test_detection_image_invalid_id_format_returns_404_not_500(
    api_app_factory: Callable,
) -> None:
    client, token, _ = _authed_client(api_app_factory, [])

    response = client.get(
        "/detections/not-a-valid-object-id/image",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


def test_detection_image_unknown_id_returns_404(api_app_factory: Callable) -> None:
    client, token, _ = _authed_client(api_app_factory, [])

    response = client.get(
        f"/detections/{ObjectId()}/image", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 404


def test_detections_endpoints_do_not_require_admin_role(api_app_factory: Callable) -> None:
    # Any authenticated role (including 'normal') can read detections; there's
    # no admin-only gate on the read endpoints of this router (DELETE is
    # admin-only, see test_delete_detection_*).
    documents = [_make_document(captured_at="2026-07-01T10:00:00+00:00")]
    client, token, _ = _authed_client(api_app_factory, documents)

    response = client.get("/detections/latest", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200


def test_detections_return_503_when_mongo_not_configured_and_no_override(
    api_app_factory: Callable,
) -> None:
    app, users_db, _ = api_app_factory()
    create_user(users_db, AUTH_HEADER_USERNAME, "s3cr3t", "normal")
    client = TestClient(app)
    login = client.post(
        "/auth/login", json={"username": AUTH_HEADER_USERNAME, "password": "s3cr3t"}
    )
    token = login.json()["access_token"]

    response = client.get("/detections/latest", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 503


def test_list_detections_defaults_to_captured_at_descending(api_app_factory: Callable) -> None:
    documents = [
        _make_document(captured_at="2026-07-01T10:00:00+00:00"),
        _make_document(captured_at="2026-07-03T10:00:00+00:00"),
        _make_document(captured_at="2026-07-02T10:00:00+00:00"),
    ]
    client, token, _ = _authed_client(api_app_factory, documents)

    response = client.get("/detections", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    dates = [item["captured_at"] for item in response.json()["items"]]
    assert dates == sorted(dates, reverse=True)


def test_list_detections_sort_order_asc_reverses_default(api_app_factory: Callable) -> None:
    documents = [
        _make_document(captured_at="2026-07-01T10:00:00+00:00"),
        _make_document(captured_at="2026-07-03T10:00:00+00:00"),
        _make_document(captured_at="2026-07-02T10:00:00+00:00"),
    ]
    client, token, _ = _authed_client(api_app_factory, documents)

    response = client.get(
        "/detections?sort_order=asc", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    dates = [item["captured_at"] for item in response.json()["items"]]
    assert dates == sorted(dates)


def test_list_detections_sort_by_camera_id(api_app_factory: Callable) -> None:
    documents = [
        _make_document(camera_id="CAM3", captured_at="2026-07-01T10:00:00+00:00"),
        _make_document(camera_id="CAM1", captured_at="2026-07-02T10:00:00+00:00"),
        _make_document(camera_id="CAM2", captured_at="2026-07-03T10:00:00+00:00"),
    ]
    client, token, _ = _authed_client(api_app_factory, documents)

    response = client.get(
        "/detections?sort_by=camera_id&sort_order=asc",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert [item["camera_id"] for item in response.json()["items"]] == ["CAM1", "CAM2", "CAM3"]


def test_list_detections_sort_by_criticidad(api_app_factory: Callable) -> None:
    documents = [
        _make_document(criticidad="rojo", captured_at="2026-07-01T10:00:00+00:00"),
        _make_document(criticidad="amarillo", captured_at="2026-07-02T10:00:00+00:00"),
        _make_document(criticidad="verde", captured_at="2026-07-03T10:00:00+00:00"),
    ]
    client, token, _ = _authed_client(api_app_factory, documents)

    response = client.get(
        "/detections?sort_by=criticidad&sort_order=asc",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    # Alphabetical, since the fake sorts the raw string like Mongo would.
    assert [item["criticidad"] for item in response.json()["items"]] == [
        "amarillo",
        "rojo",
        "verde",
    ]


def test_list_detections_filters_by_criticidad(api_app_factory: Callable) -> None:
    documents = [
        _make_document(criticidad="rojo", captured_at="2026-07-01T10:00:00+00:00"),
        _make_document(criticidad="verde", captured_at="2026-07-02T10:00:00+00:00"),
    ]
    client, token, _ = _authed_client(api_app_factory, documents)

    response = client.get(
        "/detections?criticidad=rojo", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["criticidad"] == "rojo"


def test_list_detections_rejects_invalid_sort_by(api_app_factory: Callable) -> None:
    client, token, _ = _authed_client(api_app_factory, [])

    response = client.get(
        "/detections?sort_by=rtsp_url", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 422


def test_list_detections_rejects_invalid_sort_order(api_app_factory: Callable) -> None:
    client, token, _ = _authed_client(api_app_factory, [])

    response = client.get(
        "/detections?sort_order=sideways", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 422


def test_admin_can_delete_a_detection(api_app_factory: Callable) -> None:
    target = _make_document(captured_at="2026-07-01T10:00:00+00:00")
    documents = [target, _make_document(captured_at="2026-07-02T10:00:00+00:00")]
    client, token, _ = _admin_authed_client(api_app_factory, documents)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.delete(f"/detections/{target['_id']}", headers=headers)
    assert response.status_code == 204

    remaining = client.get("/detections", headers=headers).json()
    assert remaining["total"] == 1
    assert target["_id"] not in [item["id"] for item in remaining["items"]]


def test_delete_detection_requires_admin_role(api_app_factory: Callable) -> None:
    target = _make_document(captured_at="2026-07-01T10:00:00+00:00")
    client, token, _ = _authed_client(api_app_factory, [target])

    response = client.delete(
        f"/detections/{target['_id']}", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 403


def test_delete_unknown_detection_returns_404(api_app_factory: Callable) -> None:
    client, token, _ = _admin_authed_client(api_app_factory, [])

    response = client.delete(
        f"/detections/{ObjectId()}", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 404


def test_delete_detection_invalid_id_format_returns_404_not_500(
    api_app_factory: Callable,
) -> None:
    client, token, _ = _admin_authed_client(api_app_factory, [])

    response = client.delete(
        "/detections/not-a-valid-object-id", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 404
