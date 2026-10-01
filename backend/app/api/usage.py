from __future__ import annotations

import threading
import time

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import serialize, usage as usage_ledger
from ..config import get_settings
from ..deps import get_db, require_user
from ..models import UsageRecord
from ..providers.base import ProviderError
from ..providers.registry import openrouter_client

router = APIRouter(prefix="/usage", tags=["usage"], dependencies=[Depends(require_user)])

_balance_cache: dict = {}
_balance_lock = threading.Lock()
KEY_FIELDS = ("label", "usage", "usage_daily", "usage_weekly", "usage_monthly", "limit", "limit_remaining",
              "limit_reset", "is_free_tier")


def fetch_balance(force: bool = False) -> dict:
    s = get_settings()
    if not s.openrouter_configured:
        return {"available": False, "reason": "OPENROUTER_API_KEY não configurada no servidor."}
    with _balance_lock:
        cached = _balance_cache.get("data")
        if cached and not force and time.monotonic() - _balance_cache.get("at", 0) < 60:
            return cached
    client = openrouter_client()
    out: dict = {"available": False, "balance": None, "source": None, "key": None, "credits": None}
    try:
        info = client.key_info()
        out["key"] = {k: info.get(k) for k in KEY_FIELDS}
    except ProviderError as exc:
        out["key_error"] = str(exc)
    try:
        credits = client.credits()
        total, used = credits.get("total_credits"), credits.get("total_usage")
        if total is not None and used is not None:
            out["credits"] = {"total_credits": total, "total_usage": used}
            out["balance"] = round(float(total) - float(used), 6)
            out["source"] = "credits"
    except ProviderError as exc:
        out["credits_error"] = str(exc)
    if out["balance"] is None and out["key"] and out["key"].get("limit_remaining") is not None:
        out["balance"] = out["key"]["limit_remaining"]
        out["source"] = "key_limit"
    out["available"] = out["balance"] is not None
    if not out["available"]:
        out["reason"] = ("A OpenRouter só informa o saldo da conta com uma chave de gerenciamento "
                         "(OPENROUTER_MANAGEMENT_KEY) ou quando a chave tem limite de gasto definido.")
    with _balance_lock:
        _balance_cache.update({"data": out, "at": time.monotonic()})
    return out


@router.get("/summary")
def summary(db: Session = Depends(get_db)) -> dict:
    data = usage_ledger.summary(db)
    data["budget"] = usage_ledger.get_budget(db)
    return data


@router.get("/balance")
def balance(refresh: bool = False) -> dict:
    return fetch_balance(force=refresh)


@router.get("/records")
def records(project_id: int | None = None, channel_id: int | None = None, limit: int = 200,
            db: Session = Depends(get_db)) -> list[dict]:
    q = select(UsageRecord)
    if project_id:
        q = q.where(UsageRecord.project_id == project_id)
    if channel_id:
        q = q.where(UsageRecord.channel_id == channel_id)
    rows = db.scalars(q.order_by(UsageRecord.id.desc()).limit(min(limit, 1000)))
    return [{
        "id": r.id, "stage": r.stage, "operation": r.operation, "provider": r.provider, "model": r.model,
        "prompt_tokens": r.prompt_tokens, "completion_tokens": r.completion_tokens, "reasoning_tokens": r.reasoning_tokens,
        "total_tokens": r.total_tokens, "units": r.units, "unit": r.unit, "cost": r.cost_usd,
        "cost_source": r.cost_source, "project_id": r.project_id, "channel_id": r.channel_id, "scene_id": r.scene_id,
        "job_id": r.job_id, "generation_id": r.generation_id, "created_at": serialize.iso(r.created_at),
    } for r in rows]
