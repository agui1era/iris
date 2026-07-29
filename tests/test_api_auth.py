from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from iris.users_store import create_user, set_active, set_role


def test_health_requires_no_auth(api_app_factory: Callable) -> None:
    app, _, _ = api_app_factory()
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_login_with_valid_credentials_returns_a_token(api_app_factory: Callable) -> None:
    app, users_db, _ = api_app_factory()
    create_user(users_db, "alice", "s3cr3t", "admin")
    client = TestClient(app)

    response = client.post("/auth/login", json={"username": "alice", "password": "s3cr3t"})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["username"] == "alice"
    assert body["role"] == "admin"
    assert isinstance(body["access_token"], str) and body["access_token"]


def test_login_with_wrong_password_returns_generic_error(api_app_factory: Callable) -> None:
    app, users_db, _ = api_app_factory()
    create_user(users_db, "alice", "s3cr3t", "normal")
    client = TestClient(app)

    response = client.post("/auth/login", json={"username": "alice", "password": "wrong"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Usuario o contraseña inválidos."


def test_login_with_unknown_username_returns_the_same_generic_error(
    api_app_factory: Callable,
) -> None:
    app, _, _ = api_app_factory()
    client = TestClient(app)

    response = client.post("/auth/login", json={"username": "nobody", "password": "whatever"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Usuario o contraseña inválidos."


def test_login_with_inactive_user_returns_the_same_generic_error(
    api_app_factory: Callable,
) -> None:
    app, users_db, _ = api_app_factory()
    create_user(users_db, "alice", "s3cr3t", "normal")
    set_active(users_db, "alice", False)
    client = TestClient(app)

    response = client.post("/auth/login", json={"username": "alice", "password": "s3cr3t"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Usuario o contraseña inválidos."


def test_me_without_token_is_rejected(api_app_factory: Callable) -> None:
    app, _, _ = api_app_factory()
    client = TestClient(app)

    response = client.get("/auth/me")

    assert response.status_code == 401


def test_me_with_invalid_token_is_rejected(api_app_factory: Callable) -> None:
    app, _, _ = api_app_factory()
    client = TestClient(app)

    response = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})

    assert response.status_code == 401


def test_me_with_valid_token_returns_username_and_role(api_app_factory: Callable) -> None:
    app, users_db, _ = api_app_factory()
    create_user(users_db, "bob", "s3cr3t", "normal")
    client = TestClient(app)
    login_response = client.post("/auth/login", json={"username": "bob", "password": "s3cr3t"})
    token = login_response.json()["access_token"]

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {"username": "bob", "role": "normal"}


def test_deactivating_user_immediately_revokes_existing_token(
    api_app_factory: Callable,
) -> None:
    app, users_db, _ = api_app_factory()
    create_user(users_db, "bob", "s3cr3t", "normal")
    client = TestClient(app)
    token = client.post(
        "/auth/login",
        json={"username": "bob", "password": "s3cr3t"},
    ).json()["access_token"]

    set_active(users_db, "bob", False)
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_role_change_is_applied_to_existing_token(
    api_app_factory: Callable,
) -> None:
    app, users_db, _ = api_app_factory()
    create_user(users_db, "bob", "s3cr3t", "admin")
    client = TestClient(app)
    token = client.post(
        "/auth/login",
        json={"username": "bob", "password": "s3cr3t"},
    ).json()["access_token"]

    set_role(users_db, "bob", "normal")
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {"username": "bob", "role": "normal"}


def test_create_app_without_auth_jwt_secret_raises(api_app_factory: Callable) -> None:
    with pytest.raises(RuntimeError, match="AUTH_JWT_SECRET"):
        api_app_factory(AUTH_JWT_SECRET="")
