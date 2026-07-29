from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from iris.users_store import (
    User,
    UsersStoreError,
    create_user,
    list_users,
    set_active,
    set_role,
)


def _resolved_config_db_path(config_db_path: str | None) -> Path:
    return (
        Path(config_db_path).expanduser()
        if config_db_path is not None
        else Path(os.environ.get("IRIS_CONFIG_DB", "data/config.db")).expanduser()
    )


def _parse_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise argparse.ArgumentTypeError("Usa 'true' o 'false'.")


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="iris-users",
        description="Administración de usuarios y roles de IRIS.",
    )
    parser.add_argument(
        "--config-db",
        default=None,
        metavar="PATH",
        help=(
            "Ruta al archivo SQLite de usuarios. Sobrescribe IRIS_CONFIG_DB "
            "y el valor por defecto data/config.db."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="Crea un usuario nuevo.")
    create_parser.add_argument("--username", required=True)
    create_parser.add_argument("--role", required=True, choices=["admin", "normal"])

    subparsers.add_parser("list", help="Lista los usuarios existentes.")

    set_role_parser = subparsers.add_parser("set-role", help="Cambia el rol de un usuario.")
    set_role_parser.add_argument("--username", required=True)
    set_role_parser.add_argument("--role", required=True, choices=["admin", "normal"])

    set_active_parser = subparsers.add_parser("set-active", help="Activa o desactiva un usuario.")
    set_active_parser.add_argument("--username", required=True)
    set_active_parser.add_argument(
        "--active", required=True, type=_parse_bool, metavar="true|false"
    )

    return parser.parse_args(argv)


def _print_users_table(users: list[User]) -> None:
    headers = ("username", "role", "is_active", "created_at")
    rows = [(user.username, user.role, str(user.is_active), user.created_at) for user in users]
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def _format(row: tuple[str, ...]) -> str:
        return "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row))

    print(_format(headers))
    for row in rows:
        print(_format(row))


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    db_path = _resolved_config_db_path(args.config_db)

    if args.command == "create":
        password = getpass.getpass("Contraseña: ")
        confirm = getpass.getpass("Confirma la contraseña: ")
        if password != confirm:
            print("Error: las contraseñas no coinciden.", file=sys.stderr)
            return 1
        try:
            user = create_user(db_path, args.username, password, args.role)
        except UsersStoreError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(f"Usuario '{user.username}' creado con rol '{user.role}'.")
        return 0

    if args.command == "list":
        users = list_users(db_path)
        if not users:
            print("No hay usuarios registrados.")
            return 0
        _print_users_table(users)
        return 0

    if args.command == "set-role":
        try:
            set_role(db_path, args.username, args.role)
        except UsersStoreError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(f"Usuario '{args.username}' ahora tiene el rol '{args.role}'.")
        return 0

    if args.command == "set-active":
        try:
            set_active(db_path, args.username, args.active)
        except UsersStoreError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        estado = "activo" if args.active else "inactivo"
        print(f"Usuario '{args.username}' ahora está {estado}.")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
