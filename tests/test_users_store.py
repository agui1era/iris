from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from iris.users_store import (
    UsersStoreError,
    create_user,
    get_user,
    list_users,
    set_active,
    set_role,
    verify_credentials,
)


def test_create_user_then_verify_credentials_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "users.db"

    created = create_user(path, "alice", "s3cr3t", "admin")

    assert created.username == "alice"
    assert created.role == "admin"
    assert created.is_active is True

    verified = verify_credentials(path, "alice", "s3cr3t")

    assert verified is not None
    assert verified.username == "alice"
    assert verified.role == "admin"


def test_verify_credentials_rejects_wrong_password(tmp_path: Path) -> None:
    path = tmp_path / "users.db"
    create_user(path, "alice", "s3cr3t", "normal")

    assert verify_credentials(path, "alice", "wrong-password") is None


def test_verify_credentials_rejects_unknown_username(tmp_path: Path) -> None:
    path = tmp_path / "users.db"
    create_user(path, "alice", "s3cr3t", "normal")

    assert verify_credentials(path, "bob", "s3cr3t") is None


def test_verify_credentials_rejects_inactive_user_even_with_correct_password(
    tmp_path: Path,
) -> None:
    path = tmp_path / "users.db"
    create_user(path, "alice", "s3cr3t", "normal")

    set_active(path, "alice", False)

    assert verify_credentials(path, "alice", "s3cr3t") is None


def test_create_user_with_duplicate_username_raises_and_leaves_original_untouched(
    tmp_path: Path,
) -> None:
    path = tmp_path / "users.db"
    create_user(path, "alice", "s3cr3t", "normal")

    with pytest.raises(UsersStoreError):
        create_user(path, "alice", "another-password", "admin")

    original = get_user(path, "alice")
    assert original is not None
    assert original.role == "normal"
    assert verify_credentials(path, "alice", "s3cr3t") is not None


def test_create_user_with_invalid_role_raises(tmp_path: Path) -> None:
    path = tmp_path / "users.db"

    with pytest.raises(UsersStoreError):
        create_user(path, "alice", "s3cr3t", "superuser")


def test_set_role_with_invalid_role_raises(tmp_path: Path) -> None:
    path = tmp_path / "users.db"
    create_user(path, "alice", "s3cr3t", "normal")

    with pytest.raises(UsersStoreError):
        set_role(path, "alice", "superuser")


def test_set_role_and_set_active_persist_and_are_visible(tmp_path: Path) -> None:
    path = tmp_path / "users.db"
    create_user(path, "alice", "s3cr3t", "normal")

    set_role(path, "alice", "admin")
    set_active(path, "alice", False)

    fetched = get_user(path, "alice")
    assert fetched is not None
    assert fetched.role == "admin"
    assert fetched.is_active is False

    listed = list_users(path)
    assert listed == [fetched]


def test_set_role_on_unknown_username_raises(tmp_path: Path) -> None:
    path = tmp_path / "users.db"

    with pytest.raises(UsersStoreError):
        set_role(path, "nobody", "admin")


def test_set_active_on_unknown_username_raises(tmp_path: Path) -> None:
    path = tmp_path / "users.db"

    with pytest.raises(UsersStoreError):
        set_active(path, "nobody", True)


def test_list_users_returns_multiple_users_ordered_by_username(tmp_path: Path) -> None:
    path = tmp_path / "users.db"
    create_user(path, "carol", "s3cr3t", "normal")
    create_user(path, "alice", "s3cr3t", "admin")
    create_user(path, "bob", "s3cr3t", "normal")

    usernames = [user.username for user in list_users(path)]

    assert usernames == ["alice", "bob", "carol"]


def test_password_hash_is_never_the_plaintext_password(tmp_path: Path) -> None:
    path = tmp_path / "users.db"

    create_user(path, "alice", "s3cr3t", "normal")

    connection = sqlite3.connect(path)
    try:
        password_hash = connection.execute(
            "SELECT password_hash FROM users WHERE username = ?", ("alice",)
        ).fetchone()[0]
    finally:
        connection.close()

    assert password_hash != "s3cr3t"
    assert password_hash.startswith("$2b$")
