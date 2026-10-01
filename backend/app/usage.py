"""Livro-caixa de consumo: registro, agregações por etapa/projeto/canal e limites de gasto."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .models import AppSetting, Asset, Channel, Job, Project, UsageRecord, utcnow
from .providers.base import Usage

log = logging.getLogger(__name__)

STAGE_LABELS = {
    "script": "Roteiro",
    "scenes": "Cenas",
    "visuals": "Imagens/Vídeos",
    "narration": "Narração",
    "thumbnail": "Thumbnail",
    "metadata": "Título e descrição",
    "learning": "Skill / aprendizado",
    "export": "Exportação",
}


class BudgetExceeded(Exception):
    pass


def record(
    db: Session,
    usage: Usage,
    *,
    stage: str,
    job_id: int | None = None,
    channel_id: int | None = None,
    project_id: int | None = None,
    scene_id: int | None = None,
    meta: dict[str, Any] | None = None,
) -> UsageRecord:
    rec = UsageRecord(
        job_id=job_id, channel_id=channel_id, project_id=project_id, scene_id=scene_id, stage=stage,
        operation=usage.operation, provider=usage.provider, model=usage.model, generation_id=usage.generation_id,
        prompt_tokens=usage.prompt_tokens, completion_tokens=usage.completion_tokens,
        reasoning_tokens=usage.reasoning_tokens,
        total_tokens=usage.total_tokens or (usage.prompt_tokens + usage.completion_tokens),
        units=usage.units, unit=usage.unit, cost_usd=usage.cost_usd, cost_source=usage.cost_source,
        meta={**(usage.meta or {}), **(meta or {})},
    )
    db.add(rec)
    if job_id and usage.cost_usd:
        job = db.get(Job, job_id)
        if job is not None:
            job.cost_usd = (job.cost_usd or 0.0) + usage.cost_usd
    return rec


# ------------------------------------------------------------------ limites de gasto


def get_budget(db: Session) -> dict[str, float | None]:
    row = db.get(AppSetting, "budget")
    value = row.value if row and isinstance(row.value, dict) else {}
    return {
        "daily_limit_usd": value.get("daily_limit_usd"),
        "project_limit_usd": value.get("project_limit_usd"),
    }


def save_budget(db: Session, daily: float | None, project: float | None) -> dict[str, float | None]:
    value = {
        "daily_limit_usd": float(daily) if daily not in (None, "") and float(daily) > 0 else None,
        "project_limit_usd": float(project) if project not in (None, "") and float(project) > 0 else None,
    }
    row = db.get(AppSetting, "budget")
    if row is None:
        db.add(AppSetting(key="budget", value=value))
    else:
        row.value = value
        row.updated_at = utcnow()
    return value


def _sum(db: Session, *where) -> float:
    return float(db.scalar(select(func.coalesce(func.sum(UsageRecord.cost_usd), 0.0)).where(*where)) or 0.0)


def spent_since(db: Session, since) -> float:
    return _sum(db, UsageRecord.created_at >= since)


def spent_project(db: Session, project_id: int) -> float:
    return _sum(db, UsageRecord.project_id == project_id)


def check_budget(db: Session, project_id: int | None) -> None:
    budget = get_budget(db)
    daily = budget["daily_limit_usd"]
    if daily:
        start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        spent = spent_since(db, start)
        if spent >= daily:
            raise BudgetExceeded(
                f"Limite diário de gasto atingido (US$ {spent:.2f} de US$ {daily:.2f}). "
                "Aumente o limite em Configurações para continuar."
            )
    limit = budget["project_limit_usd"]
    if limit and project_id:
        spent = spent_project(db, project_id)
        if spent >= limit:
            raise BudgetExceeded(
                f"Limite de gasto por projeto atingido (US$ {spent:.2f} de US$ {limit:.2f}). "
                "Aumente o limite em Configurações para continuar."
            )


# ------------------------------------------------------------------ agregações


def _agg_columns():
    return (
        func.coalesce(func.sum(UsageRecord.cost_usd), 0.0).label("cost"),
        func.coalesce(func.sum(UsageRecord.prompt_tokens), 0).label("tokens_in"),
        func.coalesce(func.sum(UsageRecord.completion_tokens), 0).label("tokens_out"),
        func.coalesce(func.sum(UsageRecord.total_tokens), 0).label("tokens"),
        func.count(UsageRecord.id).label("calls"),
        func.coalesce(func.sum(case((UsageRecord.cost_source == "pending", 1), else_=0)), 0).label("pending"),
    )


def _row(r) -> dict[str, Any]:
    return {
        "cost": round(float(r.cost or 0), 6),
        "tokens_in": int(r.tokens_in or 0),
        "tokens_out": int(r.tokens_out or 0),
        "tokens": int(r.tokens or 0),
        "calls": int(r.calls or 0),
        "pending": int(r.pending or 0),
    }


def by_stage(db: Session, *where) -> list[dict[str, Any]]:
    rows = db.execute(select(UsageRecord.stage, *_agg_columns()).where(*where).group_by(UsageRecord.stage)).all()
    found = {r.stage: _row(r) for r in rows}
    out = []
    for stage, label in STAGE_LABELS.items():
        data = found.pop(stage, None) or {"cost": 0.0, "tokens_in": 0, "tokens_out": 0, "tokens": 0, "calls": 0, "pending": 0}
        out.append({"stage": stage, "label": label, **data})
    for stage, data in found.items():
        out.append({"stage": stage, "label": stage, **data})
    return out


def totals(db: Session, *where) -> dict[str, Any]:
    r = db.execute(select(*_agg_columns()).where(*where)).one()
    return _row(r)


def project_costs(db: Session, project_id: int) -> dict[str, Any]:
    cond = (UsageRecord.project_id == project_id,)
    return {"total": totals(db, *cond), "stages": by_stage(db, *cond), "models": by_model(db, *cond)}


def by_model(db: Session, *where) -> list[dict[str, Any]]:
    rows = db.execute(
        select(UsageRecord.model, UsageRecord.operation, *_agg_columns())
        .where(*where).group_by(UsageRecord.model, UsageRecord.operation)
    ).all()
    out = [{"model": r.model, "operation": r.operation, **_row(r)} for r in rows]
    return sorted(out, key=lambda x: -x["cost"])


def summary(db: Session) -> dict[str, Any]:
    now = utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = today.replace(day=1)
    channels = db.execute(
        select(UsageRecord.channel_id, Channel.name, *_agg_columns())
        .join(Channel, Channel.id == UsageRecord.channel_id, isouter=True)
        .group_by(UsageRecord.channel_id, Channel.name)
    ).all()
    projects = db.execute(
        select(UsageRecord.project_id, Project.title, Project.channel_id, *_agg_columns())
        .join(Project, Project.id == UsageRecord.project_id, isouter=True)
        .where(UsageRecord.project_id.is_not(None))
        .group_by(UsageRecord.project_id, Project.title, Project.channel_id)
    ).all()
    day_col = func.date(UsageRecord.created_at)
    days = db.execute(
        select(day_col.label("day"), func.coalesce(func.sum(UsageRecord.cost_usd), 0.0).label("cost"))
        .where(UsageRecord.created_at >= today - timedelta(days=29))
        .group_by(day_col).order_by(day_col)
    ).all()
    return {
        "total": totals(db),
        "today": totals(db, UsageRecord.created_at >= today),
        "last_7_days": totals(db, UsageRecord.created_at >= today - timedelta(days=6)),
        "month": totals(db, UsageRecord.created_at >= month),
        "stages": by_stage(db),
        "models": by_model(db),
        "channels": sorted(
            [{"channel_id": r.channel_id, "name": r.name or "—", **_row(r)} for r in channels],
            key=lambda x: -x["cost"],
        ),
        "projects": sorted(
            [{"project_id": r.project_id, "title": r.title or "(removido)", "channel_id": r.channel_id, **_row(r)}
             for r in projects],
            key=lambda x: -x["cost"],
        )[:50],
        "days": [{"day": str(r.day), "cost": round(float(r.cost or 0), 6)} for r in days],
    }


# ------------------------------------------------------------------ custo pendente (TTS etc.)


def reconcile_pending(db: Session, client, *, max_age_days: int = 3, limit: int = 40) -> int:
    """Busca na OpenRouter o custo real das gerações que ainda estão 'pending'."""
    cutoff = utcnow() - timedelta(days=max_age_days)
    pending = db.scalars(
        select(UsageRecord).where(UsageRecord.cost_source == "pending", UsageRecord.generation_id.is_not(None))
        .order_by(UsageRecord.id).limit(limit)
    ).all()
    fixed = 0
    for rec in pending:
        if rec.created_at < cutoff:
            rec.cost_source = "unknown"
            continue
        try:
            info = client.generation(rec.generation_id)
        except Exception as exc:  # noqa: BLE001 - rede instável não deve derrubar o worker
            log.info("custo pendente %s ainda indisponível: %s", rec.generation_id, exc)
            continue
        if not info or info.get("total_cost") is None:
            continue
        rec.cost_usd = float(info["total_cost"])
        rec.cost_source = "generation"
        if info.get("tokens_prompt") is not None and not rec.prompt_tokens:
            rec.prompt_tokens = int(info.get("tokens_prompt") or 0)
            rec.completion_tokens = int(info.get("tokens_completion") or 0)
            rec.total_tokens = rec.prompt_tokens + rec.completion_tokens
        if rec.job_id:
            job = db.get(Job, rec.job_id)
            if job is not None:
                job.cost_usd = (job.cost_usd or 0.0) + rec.cost_usd
        asset = db.scalar(select(Asset).where(Asset.generation_id == rec.generation_id))
        if asset is not None and asset.cost_usd is None:
            asset.cost_usd = rec.cost_usd
        fixed += 1
    return fixed
