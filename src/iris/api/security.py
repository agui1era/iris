from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, status

from iris.users_store import get_user

_ALGORITHM = "HS256"
_WWW_AUTHENTICATE = {"WWW-Authenticate": "Bearer"}


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    username: str
    role: str


def create_access_token(username: str, role: str, secret: str, expires_minutes: int) -> str:
    """Emite un JWT HS256 firmado con ``secret``, válido por ``expires_minutes``."""

    now = datetime.now(UTC)
    payload = {
        "sub": username,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def decode_access_token(token: str, secret: str) -> dict[str, Any]:
    """Decodifica y valida un JWT HS256. Lanza ``jwt.PyJWTError`` si es inválido."""

    return jwt.decode(token, secret, algorithms=[_ALGORITHM])


def _extract_bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization")
    if not header or not header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falta el token de autenticación.",
            headers=_WWW_AUTHENTICATE,
        )
    token = header.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falta el token de autenticación.",
            headers=_WWW_AUTHENTICATE,
        )
    return token


def get_current_user(request: Request) -> AuthenticatedUser:
    """Dependencia de FastAPI: exige y valida un Bearer JWT en la petición."""

    token = _extract_bearer_token(request)
    secret = request.app.state.config.auth_jwt_secret
    try:
        payload = decode_access_token(token, secret)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado.",
            headers=_WWW_AUTHENTICATE,
        ) from exc
    username = payload.get("sub")
    role = payload.get("role")
    if not isinstance(username, str) or not isinstance(role, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado.",
            headers=_WWW_AUTHENTICATE,
        )
    stored_user = get_user(request.app.state.users_db_path, username)
    if stored_user is None or not stored_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o usuario inactivo.",
            headers=_WWW_AUTHENTICATE,
        )
    # The database is authoritative so role changes and deactivation take
    # effect immediately instead of waiting for an up-to-eight-hour JWT.
    return AuthenticatedUser(username=username, role=stored_user.role)


def require_admin(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AuthenticatedUser:
    """Dependencia de FastAPI: exige que el usuario autenticado sea 'admin'."""

    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol 'admin' para esta operación.",
        )
    return user


# Alias reutilizables para las rutas: evitan `Depends(...)` como valor por
# defecto (flake8-bugbear B008) y son el patrón recomendado por FastAPI.
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
AdminUser = Annotated[AuthenticatedUser, Depends(require_admin)]
