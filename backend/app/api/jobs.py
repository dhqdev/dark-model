from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import serialize
from ..deps import get_db, get_or_404, require_user
from ..jobs import queue
from ..models import Channel, Job, Project

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(require_user)])


def _decorate(db: Session, jobs: list[Job]) -> list[dict]:
    pids = {j.project_id for j in jobs if j.project_id}
    cids = {j.channel_id for j in jobs if j.channel_id}
    titles = dict(db.execute(select(Project.id, Project.title).where(Project.id.in_(pids))).all()) if pids else {}
    names = dict(db.execute(select(Channel.id, Channel.name).where(Channel.id.in_(cids))).all()) if cids else {}
    out = []
    for j in jobs:
        d = serialize.job(j)
        d["project_title"] = titles.get(j.project_id)
        d["channel_name"] = names.get(j.channel_id)
        out.append(d)
    return out


@router.get("")
def list_jobs(status: str | None = None, project_id: int | None = None, channel_id: int | None = None,
              limit: int = 100, db: Session = Depends(get_db)) -> dict:
    q = select(Job).where(Job.parent_id.is_(None))
    if status == "active":
        q = q.where(Job.status.in_(queue.ACTIVE))
    elif status:
        q = q.where(Job.status == status)
    if project_id:
        q = q.where(Job.project_id == project_id)
    if channel_id:
        q = q.where(Job.channel_id == channel_id)
    jobs = list(db.scalars(q.order_by(Job.id.desc()).limit(min(limit, 300))))
    counts = dict(db.execute(select(Job.status, func.count(Job.id)).where(Job.is_group.is_(False))
                             .group_by(Job.status)).all())
    return {"jobs": _decorate(db, jobs), "counts": counts}


@router.get("/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)) -> dict:
    j = get_or_404(db, Job, job_id, "Tarefa")
    out = _decorate(db, [j])[0]
    if j.is_group:
        children = list(db.scalars(select(Job).where(Job.parent_id == j.id).order_by(Job.id)))
        out["children"] = [serialize.job(c) for c in children]
    return out


@router.post("/{job_id}/retry")
def retry(job_id: int, db: Session = Depends(get_db)) -> dict:
    j = get_or_404(db, Job, job_id, "Tarefa")
    n = queue.retry(db, j)
    if n == 0:
        raise HTTPException(400, "Nada para repetir: a tarefa não falhou.")
    db.commit()
    return {"requeued": n, "job": serialize.job(j)}


@router.post("/{job_id}/cancel")
def cancel(job_id: int, db: Session = Depends(get_db)) -> dict:
    j = get_or_404(db, Job, job_id, "Tarefa")
    queue.cancel(db, j)
    db.commit()
    return {"job": serialize.job(j)}
