"""Fila de tarefas guardada no banco.

- Cada etapa pesada vira um job; lotes ("gerar todas as imagens") são um job-grupo com filhos.
- Falhou? Só o job que falhou é repetido (retry do grupo reenfileira apenas os filhos com erro).
- O worker "reserva" um job de forma atômica (SKIP LOCKED no PostgreSQL; UPDATE condicional no SQLite).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ..db import is_postgres, session_scope
from ..models import Job, JobStatus, utcnow

LANES: dict[str, str] = {
    "script.analyze": "llm",
    "scenes.plan": "llm",
    "scene.rewrite": "llm",
    "thumbnail.concepts": "llm",
    "metadata.generate": "llm",
    "skill.draft": "llm",
    "skill.learn": "llm",
    "skill.consolidate": "llm",
    "visual.image": "image",
    "thumbnail.image": "image",
    "narration.scene": "tts",
    "visual.video": "video",
    "visual.motion": "cpu",
    "narration.merge": "cpu",
    "export.zip": "cpu",
}
STAGES: dict[str, str] = {
    "script.analyze": "script",
    "scenes.plan": "scenes",
    "scene.rewrite": "scenes",
    "visual.image": "visuals",
    "visual.video": "visuals",
    "visual.motion": "visuals",
    "narration.scene": "narration",
    "narration.merge": "narration",
    "thumbnail.concepts": "thumbnail",
    "thumbnail.image": "thumbnail",
    "metadata.generate": "metadata",
    "export.zip": "export",
    "skill.draft": "learning",
    "skill.learn": "learning",
    "skill.consolidate": "learning",
}
FREE_KINDS = {"visual.motion", "narration.merge", "export.zip"}
ACTIVE = (JobStatus.QUEUED.value, JobStatus.RUNNING.value)
TERMINAL = (JobStatus.SUCCEEDED.value, JobStatus.FAILED.value, JobStatus.CANCELED.value)


def enqueue(
    db: Session,
    kind: str,
    *,
    label: str,
    project_id: int | None = None,
    channel_id: int | None = None,
    scene_id: int | None = None,
    target_id: int | None = None,
    parent_id: int | None = None,
    payload: dict[str, Any] | None = None,
    priority: int = 0,
    max_attempts: int = 3,
    dedupe: bool = True,
) -> Job:
    if kind not in LANES:
        raise ValueError(f"tipo de job desconhecido: {kind}")
    if dedupe:
        existing = db.scalar(
            select(Job).where(
                Job.kind == kind, Job.status.in_(ACTIVE), Job.is_group.is_(False),
                Job.project_id.is_(None) if project_id is None else Job.project_id == project_id,
                Job.scene_id.is_(None) if scene_id is None else Job.scene_id == scene_id,
                Job.target_id.is_(None) if target_id is None else Job.target_id == target_id,
            )
        )
        if existing is not None:
            return existing
    job = Job(
        kind=kind, lane=LANES[kind], stage=STAGES[kind], label=label[:300], project_id=project_id,
        channel_id=channel_id, scene_id=scene_id, target_id=target_id, parent_id=parent_id,
        payload=payload or {}, priority=priority, max_attempts=max_attempts, message="na fila",
    )
    db.add(job)
    db.flush()
    if parent_id:
        update_group(db, parent_id)
    return job


def create_group(db: Session, kind: str, *, label: str, stage: str, project_id: int | None,
                 channel_id: int | None) -> Job:
    group = Job(kind=kind, lane="group", stage=stage, label=label[:300], project_id=project_id,
                channel_id=channel_id, is_group=True, status=JobStatus.QUEUED.value, message="na fila")
    db.add(group)
    db.flush()
    return group


def claim(worker_id: str, lanes: set[str]) -> int | None:
    if not lanes:
        return None
    now = utcnow()
    with session_scope() as db:
        q = (
            select(Job.id)
            .where(
                Job.status == JobStatus.QUEUED.value, Job.is_group.is_(False), Job.lane.in_(sorted(lanes)),
                or_(Job.run_after.is_(None), Job.run_after <= now),
            )
            .order_by(Job.priority.desc(), Job.id)
            .limit(1)
        )
        if is_postgres():
            q = q.with_for_update(skip_locked=True)
        job_id = db.scalar(q)
        if job_id is None:
            return None
        res = db.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == JobStatus.QUEUED.value)
            .values(status=JobStatus.RUNNING.value, worker_id=worker_id, started_at=now, heartbeat_at=now,
                    attempts=Job.attempts + 1, message="iniciando", cancel_requested=False, finished_at=None)
        )
        if res.rowcount != 1:
            return None
        job = db.get(Job, job_id)
        if job is not None and job.parent_id:
            update_group(db, job.parent_id)
        return job_id


def finish(db: Session, job: Job, status: str, *, result: dict[str, Any] | None = None, error: str = "",
           retryable: bool = False) -> None:
    now = utcnow()
    if status == JobStatus.FAILED.value and retryable and job.attempts < job.max_attempts:
        delay = min(300, 15 * 2 ** max(0, job.attempts - 1))
        job.status = JobStatus.QUEUED.value
        job.run_after = now + timedelta(seconds=delay)
        job.error = error[:4000]
        job.message = f"falhou (tentativa {job.attempts}/{job.max_attempts}); nova tentativa em {delay}s"
        job.heartbeat_at = None
    else:
        job.status = status
        job.finished_at = now
        job.heartbeat_at = now
        if status == JobStatus.SUCCEEDED.value:
            job.progress = 1.0
            job.error = ""
            job.message = (result or {}).get("message", "concluído") if isinstance(result, dict) else "concluído"
        elif status == JobStatus.CANCELED.value:
            job.message = "cancelado"
        else:
            job.error = error[:4000]
            job.message = "falhou"
        if result is not None:
            job.result = result
    if job.parent_id:
        db.flush()
        update_group(db, job.parent_id)


def update_group(db: Session, group_id: int) -> None:
    group = db.get(Job, group_id)
    if group is None or not group.is_group:
        return
    rows = db.execute(
        select(Job.status, func.count(Job.id), func.coalesce(func.sum(Job.cost_usd), 0.0))
        .where(Job.parent_id == group_id).group_by(Job.status)
    ).all()
    counts = {status: int(n) for status, n, _ in rows}
    group.cost_usd = float(sum(float(c) for *_, c in rows))
    total = sum(counts.values())
    ok = counts.get(JobStatus.SUCCEEDED.value, 0)
    failed = counts.get(JobStatus.FAILED.value, 0)
    canceled = counts.get(JobStatus.CANCELED.value, 0)
    running = counts.get(JobStatus.RUNNING.value, 0)
    queued = counts.get(JobStatus.QUEUED.value, 0)
    group.progress = (ok + failed + canceled) / total if total else 0.0
    parts = [f"{ok}/{total} concluídos"]
    if failed:
        parts.append(f"{failed} com erro")
    if canceled:
        parts.append(f"{canceled} cancelados")
    group.message = ", ".join(parts)
    group.result = {"total": total, "succeeded": ok, "failed": failed, "canceled": canceled,
                    "running": running, "queued": queued}
    if running or queued:
        group.status = JobStatus.RUNNING.value if (running or ok or failed) else JobStatus.QUEUED.value
        group.finished_at = None
        if group.started_at is None and running:
            group.started_at = utcnow()
    elif total:
        if failed:
            group.status = JobStatus.FAILED.value
            group.error = f"{failed} de {total} tarefas falharam — use 'repetir' para refazer só as que falharam"
        elif canceled == total:
            group.status = JobStatus.CANCELED.value
        else:
            group.status = JobStatus.SUCCEEDED.value
            group.error = ""
        group.finished_at = group.finished_at or utcnow()


def heartbeat(job_id: int, progress: float | None = None, message: str | None = None) -> bool:
    """Atualiza progresso. Retorna True se o usuário pediu cancelamento."""
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            return True
        job.heartbeat_at = utcnow()
        if progress is not None:
            job.progress = max(0.0, min(1.0, float(progress)))
        if message is not None:
            job.message = message[:400]
        return bool(job.cancel_requested)


def cancel(db: Session, job: Job) -> None:
    if job.is_group:
        for child in db.scalars(select(Job).where(Job.parent_id == job.id, Job.status.in_(ACTIVE))):
            _cancel_one(child)
        db.flush()
        update_group(db, job.id)
        if job.status in ACTIVE:
            job.status = JobStatus.CANCELED.value
            job.finished_at = utcnow()
    else:
        _cancel_one(job)
        if job.parent_id:
            db.flush()
            update_group(db, job.parent_id)


def _cancel_one(job: Job) -> None:
    if job.status == JobStatus.QUEUED.value:
        job.status = JobStatus.CANCELED.value
        job.finished_at = utcnow()
        job.message = "cancelado"
    elif job.status == JobStatus.RUNNING.value:
        job.cancel_requested = True
        job.message = "cancelando..."


def retry(db: Session, job: Job) -> int:
    """Reenfileira o job (ou, num grupo, apenas os filhos que falharam/cancelaram)."""
    targets = (
        list(db.scalars(select(Job).where(Job.parent_id == job.id,
                                          Job.status.in_((JobStatus.FAILED.value, JobStatus.CANCELED.value)))))
        if job.is_group else ([job] if job.status in (JobStatus.FAILED.value, JobStatus.CANCELED.value) else [])
    )
    for t in targets:
        t.status = JobStatus.QUEUED.value
        t.attempts = 0
        t.run_after = None
        t.cancel_requested = False
        t.finished_at = None
        t.progress = 0.0
        t.message = "na fila (repetição)"
    if job.is_group and targets:
        job.status = JobStatus.RUNNING.value
        job.finished_at = None
        job.error = ""
    db.flush()
    if job.is_group:
        update_group(db, job.id)
    elif job.parent_id:
        update_group(db, job.parent_id)
    return len(targets)


def recover_stale(db: Session, stale_seconds: int) -> int:
    cutoff = utcnow() - timedelta(seconds=stale_seconds)
    stale = db.scalars(
        select(Job).where(Job.status == JobStatus.RUNNING.value, Job.is_group.is_(False),
                          or_(Job.heartbeat_at.is_(None), Job.heartbeat_at < cutoff))
    ).all()
    for job in stale:
        if job.cancel_requested:
            finish(db, job, JobStatus.CANCELED.value)
        elif job.attempts < job.max_attempts:
            job.status = JobStatus.QUEUED.value
            job.run_after = None
            job.message = "worker interrompido; reenfileirado"
        else:
            finish(db, job, JobStatus.FAILED.value, error="O worker parou de responder durante a tarefa.")
    return len(stale)


def active_for(db: Session, *, project_id: int | None = None, channel_id: int | None = None) -> list[Job]:
    q = select(Job).where(Job.status.in_(ACTIVE), Job.parent_id.is_(None))
    if project_id is not None:
        q = q.where(Job.project_id == project_id)
    if channel_id is not None:
        q = q.where(Job.channel_id == channel_id)
    return list(db.scalars(q.order_by(Job.id.desc())))
