"""Cotação do dólar (USD → BRL) para mostrar custos e tetos por vídeo em reais.

A OpenRouter cobra em dólar; os tetos são definidos em reais. Ordem da cotação usada:
manual (Configurações) → ao vivo (cache de 12 h) → última cotação obtida → USD_BRL do ambiente.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from .config import get_settings
from .db import session_scope
from .models import AppSetting, utcnow

log = logging.getLogger(__name__)

KEY = "fx"
LIVE_TTL = timedelta(hours=12)
RETRY_AFTER_FAILURE = timedelta(minutes=30)
SOURCES = (
    ("https://economia.awesomeapi.com.br/json/last/USD-BRL", lambda d: d["USDBRL"]["bid"]),
    ("https://api.frankfurter.app/latest?from=USD&to=BRL", lambda d: d["rates"]["BRL"]),
)


def _stored(db: Session) -> dict[str, Any]:
    row = db.get(AppSetting, KEY)
    return dict(row.value) if row and isinstance(row.value, dict) else {}


def _store(update: dict[str, Any]) -> None:
    with session_scope() as db:
        row = db.get(AppSetting, KEY)
        value = {**(dict(row.value) if row and isinstance(row.value, dict) else {}), **update}
        if row is None:
            db.add(AppSetting(key=KEY, value=value))
        else:
            row.value = value
            row.updated_at = utcnow()


def _parse_time(value: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fetch_live() -> float | None:
    """Cotação comercial atual (compra). None se nenhuma fonte responder."""
    for url, pick in SOURCES:
        try:
            r = httpx.get(url, timeout=4.0, headers={"User-Agent": "dark-model"})
            r.raise_for_status()
            rate = float(pick(r.json()))
            if 1.0 < rate < 50.0:
                return rate
        except Exception as exc:  # noqa: BLE001 - tenta a próxima fonte
            log.info("cotação indisponível em %s: %s", url, exc)
    return None


def get_rate(db: Session) -> dict[str, Any]:
    stored = _stored(db)
    if stored.get("manual"):
        return {"rate": float(stored["manual"]), "source": "manual", "at": None, "note": "cotação fixada em Configurações"}
    now = datetime.now(timezone.utc)
    live_at = _parse_time(stored.get("live_at"))
    if stored.get("live") and live_at and now - live_at < LIVE_TTL:
        return {"rate": float(stored["live"]), "source": "live", "at": stored["live_at"], "note": "cotação do dia"}
    failed_at = _parse_time(stored.get("failed_at"))
    if get_settings().fx_auto and not (failed_at and now - failed_at < RETRY_AFTER_FAILURE):
        rate = fetch_live()
        if rate:
            stamp = now.isoformat()
            _store({"live": rate, "live_at": stamp, "failed_at": None})
            return {"rate": rate, "source": "live", "at": stamp, "note": "cotação do dia"}
        _store({"failed_at": now.isoformat()})
    if stored.get("live"):
        return {"rate": float(stored["live"]), "source": "last", "at": stored.get("live_at"),
                "note": "última cotação obtida"}
    return {"rate": float(get_settings().usd_brl), "source": "default", "at": None,
            "note": "cotação padrão (USD_BRL), sem acesso à cotação do dia"}


def save_manual(db: Session, rate: float | None) -> None:
    value = _stored(db)
    value["manual"] = float(rate) if rate and float(rate) > 0 else None
    row = db.get(AppSetting, KEY)
    if row is None:
        db.add(AppSetting(key=KEY, value=value))
    else:
        row.value = value
        row.updated_at = utcnow()
