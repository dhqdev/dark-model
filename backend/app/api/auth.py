from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from ..config import get_settings
from ..deps import require_user
from ..security import (
    COOKIE_NAME, LoginBlocked, check_rate_limit, clear_failures, create_session_token, read_session_token,
    register_failure, verify_credentials,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/status")
def status(request: Request) -> dict:
    s = get_settings()
    return {
        "configured": s.credentials_configured,
        "authenticated": bool(read_session_token(request.cookies.get(COOKIE_NAME))),
        "app_name": s.app_name,
    }


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response) -> dict:
    s = get_settings()
    if not s.credentials_configured:
        raise HTTPException(503, "Login desativado: defina APP_USERNAME e APP_PASSWORD na Stack do Portainer.")
    ip = _client_ip(request)
    try:
        check_rate_limit(ip)
    except LoginBlocked as exc:
        raise HTTPException(429, f"Muitas tentativas. Aguarde {exc.retry_after}s.",
                            headers={"Retry-After": str(exc.retry_after)}) from exc
    if not verify_credentials(body.username, body.password):
        register_failure(ip)
        raise HTTPException(401, "Usuário ou senha incorretos.")
    clear_failures(ip)
    response.set_cookie(
        COOKIE_NAME, create_session_token(), max_age=s.session_hours * 3600, httponly=True,
        secure=s.cookie_secure, samesite="lax", path="/",
    )
    return {"ok": True, "username": s.app_username}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: str = Depends(require_user)) -> dict:
    return {"username": user}
