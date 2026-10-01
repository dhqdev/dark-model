from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import catalog, pricing, serialize, tiers, usage as usage_ledger
from ..config import get_settings
from ..deps import get_db, require_user
from ..providers.base import ProviderError
from ..providers.registry import openrouter_client
from .usage import fetch_balance

router = APIRouter(tags=["settings"], dependencies=[Depends(require_user)])


class TiersIn(BaseModel):
    tiers: dict[str, dict[str, Any]]


class BudgetIn(BaseModel):
    daily_limit_usd: float | None = Field(None, ge=0)
    project_limit_usd: float | None = Field(None, ge=0)


def _catalog_status() -> dict:
    out = {}
    for kind, key in catalog.KINDS.items():
        at = catalog.fetched_at(key)
        try:
            items = catalog.get(key, refresh_if_stale=False)
        except ProviderError:
            items = []
        out[kind] = {"count": len(items or []), "fetched_at": serialize.iso(at)}
    return out


@router.get("/settings")
def get_all(db: Session = Depends(get_db)) -> dict:
    s = get_settings()
    return {
        "tiers": tiers.get_tier_settings(db),
        "resolved": tiers.resolve_all(db),
        "operations": tiers.OPERATION_LABELS,
        "budget": usage_ledger.get_budget(db),
        "providers": {"openrouter": {"configured": s.openrouter_configured, "base_url": s.openrouter_base_url,
                                     "management_key": bool(s.openrouter_management_key)}},
        "catalog": _catalog_status(),
        "app": {"env": s.app_env, "public_url": s.app_public_url, "embedded_worker": s.embedded_worker,
                "lanes": s.lanes(), "catalog_ttl_minutes": s.catalog_ttl_minutes},
    }


@router.put("/settings/tiers")
def put_tiers(body: TiersIn, db: Session = Depends(get_db)) -> dict:
    for tier, cfg in body.tiers.items():
        for op in tiers.OPERATIONS:
            model = cfg.get(op)
            if model and get_settings().openrouter_configured and not catalog.exists(tiers.CATALOG_KIND[op], model):
                raise HTTPException(400, f"Modelo '{model}' não encontrado no catálogo da OpenRouter ({op}, {tier}).")
    saved = tiers.save_tier_settings(db, body.tiers)
    db.commit()
    return {"tiers": saved, "resolved": tiers.resolve_all(db)}


@router.put("/settings/budget")
def put_budget(body: BudgetIn, db: Session = Depends(get_db)) -> dict:
    value = usage_ledger.save_budget(db, body.daily_limit_usd, body.project_limit_usd)
    db.commit()
    return value


def _per_million(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return round(v * 1_000_000, 4) if v >= 0 else None


@router.get("/catalog/{kind}")
def catalog_list(kind: str, q: str = "", limit: int = 400, resolution: str = "1K",
                 db: Session = Depends(get_db)) -> list[dict]:
    if kind not in ("text", "image", "speech", "video"):
        raise HTTPException(404, "tipo de catálogo inválido")
    if kind == "image":
        items = catalog.safe_get(catalog.KINDS["image"])
        ids = {m.get("id") for m in items}
        items += [m for m in catalog.safe_get(catalog.KINDS["image_chat"]) if m.get("id") not in ids]
    else:
        items = catalog.safe_get(catalog.KINDS[kind])
    ql = q.lower().strip()
    if kind == "image":
        catalog.prefetch_image_endpoints([str(m.get("id")) for m in items])
    out = []
    for m in items:
        mid = str(m.get("id") or "")
        if ql and ql not in mid.lower() and ql not in str(m.get("name", "")).lower():
            continue
        p = m.get("pricing") or {}
        row: dict[str, Any] = {"id": mid, "name": m.get("name") or mid, "created": m.get("created"),
                               "context_length": m.get("context_length")}
        if kind in ("text", "speech", "image"):
            row["prompt_per_m"] = _per_million(p.get("prompt"))
            row["completion_per_m"] = _per_million(p.get("completion"))
        if kind == "text":
            row["structured"] = "structured_outputs" in (m.get("supported_parameters") or [])
        if kind == "speech":
            row["voices"] = m.get("supported_voices") or []
            row["per_char"] = not float(p.get("completion") or 0)
        if kind == "image":
            row["image_api"] = "supported_parameters" in m and isinstance(m.get("supported_parameters"), dict)
            c = pricing.image_cost(db, mid, resolution)
            row.update({"per_image": c.value, "price_source": c.source, "price_note": c.note})
        if kind == "video":
            cost, note = pricing.video_skus_cost(m.get("pricing_skus") or {}, resolution="720p", duration=1)
            row.update({"per_second_720p": cost, "price_note": note, "durations": m.get("supported_durations"),
                        "resolutions": m.get("supported_resolutions"), "frame_images": m.get("supported_frame_images"),
                        "pricing_skus": m.get("pricing_skus")})
        out.append(row)
    out.sort(key=lambda r: -(r.get("created") or 0))
    return out[: max(1, min(limit, 2000))]


@router.get("/catalog/image/price")
def image_price(model: str, resolution: str = "1K", db: Session = Depends(get_db)) -> dict:
    c = pricing.image_cost(db, model, resolution)
    return {"model": model, "resolution": resolution, "cost": c.value, "source": c.source, "note": c.note}


@router.post("/catalog/refresh")
def refresh() -> dict:
    if not get_settings().openrouter_configured:
        raise HTTPException(400, "Configure OPENROUTER_API_KEY na Stack para carregar o catálogo.")
    return catalog.refresh_all()


@router.post("/settings/test-openrouter")
def test_openrouter() -> dict:
    if not get_settings().openrouter_configured:
        raise HTTPException(400, "OPENROUTER_API_KEY não configurada no servidor.")
    try:
        info = openrouter_client().key_info()
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True, "label": info.get("label"), "is_free_tier": info.get("is_free_tier"),
            "balance": fetch_balance(force=True)}
