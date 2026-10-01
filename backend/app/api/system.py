from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .. import __version__
from ..config import get_settings
from ..deps import get_db, require_user
from ..models import Job, WorkerHeartbeat, utcnow

router = APIRouter(tags=["system"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "version": __version__}


def workers_online(db: Session) -> list[dict]:
    cutoff = utcnow() - timedelta(seconds=90)
    rows = db.scalars(select(WorkerHeartbeat).where(WorkerHeartbeat.seen_at >= cutoff))
    return [{"id": w.worker_id, "host": w.hostname, "seen_at": w.seen_at.isoformat() + "Z", "info": w.info}
            for w in rows]


@router.get("/system/status", dependencies=[Depends(require_user)])
def system_status(db: Session = Depends(get_db)) -> dict:
    s = get_settings()
    counts = {f"{lane}:{status}": n for lane, status, n in db.execute(
        select(Job.lane, Job.status, func.count(Job.id)).where(Job.is_group.is_(False))
        .where(Job.status.in_(("queued", "running"))).group_by(Job.lane, Job.status)
    )}
    return {
        "version": __version__,
        "env": s.app_env,
        "workers": workers_online(db),
        "queue": counts,
        "openrouter_configured": s.openrouter_configured,
        "management_key_configured": bool(s.openrouter_management_key),
        "embedded_worker": s.embedded_worker,
        "database": db.get_bind().dialect.name,
    }
