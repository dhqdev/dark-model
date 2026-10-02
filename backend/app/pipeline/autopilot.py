"""Piloto automático: leva o projeto do roteiro ao ZIP sozinho, uma etapa de cada vez.

Não é um job: é um estado no projeto (`Project.autopilot`) e um gatilho que roda sempre que uma tarefa
de nível superior do projeto termina (`queue.DONE_HOOKS`). A cada gatilho, se nada do projeto estiver
rodando, `advance` vê qual é a primeira etapa ainda incompleta e enfileira só o que falta nela.

- Falha ou cancelamento de uma tarefa → pausa com a mensagem (o usuário corrige e retoma).
- Análise com "alto risco" de política do YouTube → pausa até o usuário confirmar.
- Cada etapa pode ser enfileirada no máximo MAX_TRIES vezes por execução: se ela termina "com sucesso"
  e continua incompleta, o piloto pausa em vez de gastar de novo em loop.
- Rede de segurança: a manutenção do worker chama `heal` para pilotos parados sem nada rodando.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import is_postgres
from ..jobs import queue
from ..models import Asset, AssetKind, Job, JobStatus, Project, utcnow
from . import text
from .common import StageError
from .narration import enqueue_project_narration
from .render import enqueue_render, render_state
from .visuals import enqueue_project_visuals

log = logging.getLogger(__name__)

STEPS: tuple[tuple[str, str], ...] = (
    ("analysis", "Análise do roteiro"),
    ("scenes", "Divisão em cenas"),
    # narração antes dos visuais: com a duração real do áudio, o movimento e o vídeo IA já saem no tempo certo
    ("narration", "Narração"),
    ("visuals", "Imagens e vídeos"),
    ("render", "Vídeo final"),
    ("metadata", "Título e descrição"),
    ("thumbnail", "Thumbnail"),
    ("export", "Pacote ZIP"),
)
LABELS = dict(STEPS)
MAX_TRIES = 2
# tarefas que o piloto não espera dar certo (aprendizados da Skill rodam depois da exportação)
IGNORED_FAILURES = ("skill.",)


def _now() -> str:
    return utcnow().isoformat() + "Z"


def _set(project: Project, **changes: Any) -> dict:
    state = dict(project.autopilot or {})
    state.update(changes, updated_at=_now())
    project.autopilot = state  # novo dict: o SQLAlchemy só percebe a mudança de JSON por atribuição
    return state


def start(db: Session, project: Project, *, ignore_risk: bool = False) -> dict:
    if text.word_count(project.script or "") < 30:
        raise StageError("Escreva ou cole o roteiro (mínimo de 30 palavras) antes de ligar o piloto automático.")
    project.autopilot = {
        "active": True, "status": "running", "step": None, "message": "iniciando", "error": "",
        "ignore_risk": ignore_risk or bool((project.autopilot or {}).get("ignore_risk")),
        "tries": {}, "started_at": _now(), "finished_at": None, "updated_at": _now(),
    }
    db.flush()
    advance(db, project)
    return project.autopilot


def stop(project: Project) -> dict:
    return _set(project, active=False, status="stopped", message="desligado pelo usuário")


def _pause(project: Project, error: str, *, reason: str = "error") -> None:
    _set(project, active=False, status="paused", error=error, reason=reason,
         message="pausado: corrija e clique em Retomar")


def _lock(db: Session, project: Project) -> Project:
    """Serializa os gatilhos do mesmo projeto (duas tarefas terminando juntas não enfileiram em dobro)."""
    if is_postgres():
        db.execute(select(Project.id).where(Project.id == project.id).with_for_update())
        db.refresh(project)
    return project


def _busy(db: Session, project_id: int) -> bool:
    return bool(db.scalar(select(Job.id).where(Job.project_id == project_id, Job.parent_id.is_(None),
                                               Job.status.in_(queue.ACTIVE)).limit(1)))


def _assets(db: Session, project: Project, kind: str) -> list[Asset]:
    return list(db.scalars(select(Asset).where(Asset.project_id == project.id, Asset.kind == kind)
                           .order_by(Asset.id.desc())))


def _enqueue_step(db: Session, project: Project, step: str) -> Job | None:
    """Enfileira o que falta na etapa. None = a etapa já está completa."""
    p = project
    script_hash = text.content_hash(p.script or "")
    common = dict(project_id=p.id, channel_id=p.channel_id)
    if step == "analysis":
        if p.analysis and p.analysis_script_hash == script_hash:
            return None
        return queue.enqueue(db, "script.analyze", label=f"Análise do roteiro — {p.title[:60]}", **common)
    if step == "scenes":
        scenes = list(p.scenes)
        stale = bool(scenes) and p.scenes_script_hash != script_hash
        generated = any(s.image_asset_id or s.audio_asset_id or s.clip_asset_id for s in scenes)
        # cenas desatualizadas só são refeitas se nada foi gerado nelas (refazer apagaria imagens e áudios pagos)
        if scenes and not (stale and not generated):
            return None
        return queue.enqueue(db, "scenes.plan", label=f"Divisão em cenas — {p.title[:60]}",
                             payload={"replace": True}, **common)
    if step == "visuals":
        job = enqueue_project_visuals(db, p, scope="missing")
        if job is not None and p.status in ("draft", "script", "scenes"):
            p.status = "production"
        return job
    if step == "narration":
        return enqueue_project_narration(db, p, scope="missing")
    if step == "render":
        state = render_state(db, p)
        if state["last"] is not None and not state["outdated"]:
            return None
        if not state["can_render"]:
            raise StageError("Faltam imagens ou narração em algumas cenas para montar o vídeo.")
        return enqueue_render(db, p, auto=True)
    if step == "metadata":
        if p.metadata_suggestions:
            return None
        return queue.enqueue(db, "metadata.generate", label=f"Título e descrição — {p.title[:60]}", **common)
    if step == "thumbnail":
        if p.concepts:
            return None
        group = queue.create_group(db, "thumbnail.batch", label=f"Thumbnails — {p.title[:60]}", stage="thumbnail",
                                   **common)
        queue.enqueue(db, "thumbnail.concepts", label="Conceitos de thumbnail", parent_id=group.id, dedupe=False,
                      **common)
        return group
    if step == "export":
        exports = _assets(db, p, AssetKind.EXPORT.value)
        if exports:
            newest = db.scalar(select(Asset.created_at).where(Asset.project_id == p.id,
                                                              Asset.kind != AssetKind.EXPORT.value)
                               .order_by(Asset.created_at.desc()).limit(1))
            if newest is None or newest <= exports[0].created_at:
                return None
        return queue.enqueue(db, "export.zip", label=f"Exportação — {p.title[:60]}",
                             payload={"include_clips": True, "gap": 0.0}, **common)
    raise KeyError(step)


def advance(db: Session, project: Project, finished: Job | None = None) -> None:
    project = _lock(db, project)
    state = project.autopilot or {}
    if not state.get("active"):
        return
    if finished is not None and finished.status in (JobStatus.FAILED.value, JobStatus.CANCELED.value) \
            and not finished.kind.startswith(IGNORED_FAILURES):
        what = "cancelada" if finished.status == JobStatus.CANCELED.value else (finished.error or "falhou")
        _pause(project, f"{finished.label}: {what}")
        return
    if _busy(db, project.id):
        return
    tries = dict(state.get("tries") or {})
    for step, label in STEPS:
        if step == "scenes" and not state.get("ignore_risk"):
            verdict = ((project.analysis or {}).get("ai") or {}).get("verdict")
            if verdict == "high_risk":
                _pause(project, "A análise apontou ALTO RISCO de política do YouTube. Revise o roteiro na aba "
                                "Roteiro ou continue mesmo assim.", reason="risk")
                return
        try:
            job = _enqueue_step(db, project, step)
        except StageError as exc:
            _pause(project, f"{label}: {exc}")
            return
        if job is None:
            continue
        if tries.get(step, 0) >= MAX_TRIES:
            # a etapa já rodou e continua incompleta: não gasta de novo em loop
            _pause(project, f"{label}: a etapa terminou mas continua incompleta. Veja a aba e a fila.")
            queue.cancel(db, job)
            return
        tries[step] = tries.get(step, 0) + 1
        _set(project, step=step, status="running", message=f"{label}: {job.label}", error="", tries=tries)
        return
    _set(project, active=False, status="done", step=None, message="projeto pronto: vídeo final e pacote ZIP gerados",
         error="", finished_at=_now())


def _on_done(db: Session, job: Job) -> None:
    if not job.project_id:
        return
    project = db.get(Project, job.project_id)
    if project is not None and (project.autopilot or {}).get("active"):
        advance(db, project, job)


queue.DONE_HOOKS.append(_on_done)


def heal(db: Session, idle_seconds: int = 60) -> int:
    """Pilotos ligados sem nada rodando há um tempo (gatilho perdido): avança de novo."""
    cutoff = (utcnow() - timedelta(seconds=idle_seconds)).isoformat() + "Z"
    healed = 0
    for project in db.scalars(select(Project).where(Project.autopilot.is_not(None))):
        state = project.autopilot or {}
        if state.get("active") and str(state.get("updated_at") or "") < cutoff and not _busy(db, project.id):
            log.info("piloto automático do projeto %s retomado pela manutenção", project.id)
            advance(db, project)
            healed += 1
    return healed
