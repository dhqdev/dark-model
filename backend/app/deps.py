"""Dependências das rotas: sessão do banco e usuário autenticado."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from .db import SessionLocal
from .security import COOKIE_NAME, read_session_token


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def require_user(request: Request) -> str:
    user = read_session_token(request.cookies.get(COOKIE_NAME))
    if not user:
        raise HTTPException(status_code=401, detail="Sessão expirada. Entre novamente.")
    return user


def get_or_404(db: Session, model, obj_id: int, what: str = "registro"):
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{what} não encontrado")
    return obj
