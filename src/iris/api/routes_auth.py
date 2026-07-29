from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from iris.users_store import verify_credentials

from .security import CurrentUser, create_access_token

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    username: str
    role: str


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request) -> LoginResponse:
    config = request.app.state.config
    user = verify_credentials(request.app.state.users_db_path, body.username, body.password)
    if user is None:
        # Mensaje genérico a propósito: no debe revelar si el usuario existe
        # o si sólo la contraseña fue incorrecta.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña inválidos.",
        )
    token = create_access_token(
        user.username,
        user.role,
        config.auth_jwt_secret,
        config.auth_jwt_expires_minutes,
    )
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        username=user.username,
        role=user.role,
    )


@router.get("/me")
def me(user: CurrentUser) -> dict[str, str]:
    return {"username": user.username, "role": user.role}
