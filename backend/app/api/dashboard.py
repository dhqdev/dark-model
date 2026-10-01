from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import serialize, usage as usage_ledger
from ..config import get_settings
from ..deps import get_db, require_user
from ..jobs import queue
from ..models import Asset, Channel, Job, JobStatus, Project, Scene, UsageRecord, utcnow
from ..pipeline import files
from .jobs import _decorate
from .system import workers_online

router = APIRouter(tags=["dashboard"], dependencies=[Depends(require_user)])


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)) -> dict:
    now = utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = today.replace(day=1)
    projects = list(db.scalars(select(Project).where(Project.archived.is_(False)).order_by(Project.updated_at.desc()).limit(8)))
    ids = [p.id for p in projects]
    costs = dict(db.execute(select(UsageRecord.project_id, func.coalesce(func.sum(UsageRecord.cost_usd), 0.0))
                            .where(UsageRecord.project_id.in_(ids)).group_by(UsageRecord.project_id)).all()) if ids else {}
    scenes = dict(db.execute(select(Scene.project_id, func.count(Scene.id)).where(Scene.project_id.in_(ids))
                             .group_by(Scene.project_id)).all()) if ids else {}
    channel_names = dict(db.execute(select(Channel.id, Channel.name)).all())
    sizes = files.project_sizes(db, ids)
    recent = []
    for p in projects:
        d = serialize.project_summary(p, costs.get(p.id), scenes.get(p.id, 0), sizes.get(p.id, 0))
        d["channel_name"] = channel_names.get(p.channel_id)
        recent.append(d)
    status_counts = dict(db.execute(select(Project.status, func.count(Project.id)).where(Project.archived.is_(False))
                                    .group_by(Project.status)).all())
    queue_counts = dict(db.execute(select(Job.status, func.count(Job.id)).where(Job.is_group.is_(False),
                                   Job.status.in_(queue.ACTIVE)).group_by(Job.status)).all())
    failures = list(db.scalars(select(Job).where(Job.status == JobStatus.FAILED.value, Job.parent_id.is_(None),
                                                 Job.finished_at >= now - timedelta(days=2))
                               .order_by(Job.id.desc()).limit(5)))
    active = list(db.scalars(select(Job).where(Job.status.in_(queue.ACTIVE), Job.parent_id.is_(None))
                             .order_by(Job.id.desc()).limit(8)))
    return {
        "counts": {
            "channels": db.scalar(select(func.count(Channel.id)).where(Channel.archived.is_(False))) or 0,
            "projects": sum(status_counts.values()),
            "projects_by_status": status_counts,
            "storage_bytes": int(db.scalar(select(func.coalesce(func.sum(Asset.size_bytes), 0))) or 0),
        },
        "queue": {"queued": queue_counts.get("queued", 0), "running": queue_counts.get("running", 0)},
        "costs": {
            "today": usage_ledger.totals(db, UsageRecord.created_at >= today),
            "month": usage_ledger.totals(db, UsageRecord.created_at >= month),
            "total": usage_ledger.totals(db),
        },
        "budget": usage_ledger.get_budget(db),
        "recent_projects": recent,
        "active_jobs": _decorate(db, active),
        "recent_failures": _decorate(db, failures),
        "workers": workers_online(db),
        "openrouter_configured": get_settings().openrouter_configured,
    }
