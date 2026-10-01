from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import serialize, usage as usage_ledger
from ..deps import get_db, get_or_404, require_user
from ..jobs import queue
from ..models import Asset, AssetKind, Channel, FeedbackEvent, Job, Project, Quality, Scene, UsageRecord, utcnow
from ..pipeline import text
from ..pipeline.common import StageError, scene_timeline, tts_settings
from ..pipeline.estimate import estimate_project
from ..pipeline.narration import enqueue_project_narration
from ..pipeline.visuals import enqueue_project_visuals
from ..storage import get_storage

router = APIRouter(prefix="/projects", tags=["projects"], dependencies=[Depends(require_user)])


class ProjectIn(BaseModel):
    channel_id: int
    title: str = Field(min_length=1, max_length=300)
    quality: Quality | None = None
    script: str = ""
    notes: str = ""
    target_minutes: float | None = Field(None, ge=1, le=240)


class ProjectPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=300)
    quality: Quality | None = None
    script: str | None = None
    notes: str | None = None
    target_minutes: float | None = Field(None, ge=0, le=240)
    selected_title: str | None = Field(None, max_length=300)
    description: str | None = None
    tags: list[str] | None = None
    archived: bool | None = None


class PlanIn(BaseModel):
    replace: bool = False


class ScopeIn(BaseModel):
    scope: str = Field("missing", pattern="^(missing|all)$")
    scene_ids: list[int] | None = None


class ThumbIn(BaseModel):
    count: int | None = Field(None, ge=1, le=8)
    variations: int | None = Field(None, ge=1, le=4)


class ExportIn(BaseModel):
    include_clips: bool = True
    gap: float = Field(0.0, ge=0, le=3)


class MergeIn(BaseModel):
    gap: float = Field(0.0, ge=0, le=3)


def _project(db: Session, project_id: int) -> Project:
    return get_or_404(db, Project, project_id, "Projeto")


def _job_out(job: Job | None, nothing: str) -> dict:
    if job is None:
        return {"job": None, "message": nothing}
    return {"job": serialize.job(job), "message": job.label}


@router.get("")
def list_projects(channel_id: int | None = None, include_archived: bool = False, db: Session = Depends(get_db)) -> list[dict]:
    q = select(Project).order_by(Project.updated_at.desc())
    if channel_id is not None:
        q = q.where(Project.channel_id == channel_id)
    if not include_archived:
        q = q.where(Project.archived.is_(False))
    projects = list(db.scalars(q))
    ids = [p.id for p in projects]
    costs = dict(db.execute(select(UsageRecord.project_id, func.coalesce(func.sum(UsageRecord.cost_usd), 0.0))
                            .where(UsageRecord.project_id.in_(ids)).group_by(UsageRecord.project_id)).all()) if ids else {}
    scenes = dict(db.execute(select(Scene.project_id, func.count(Scene.id)).where(Scene.project_id.in_(ids))
                             .group_by(Scene.project_id)).all()) if ids else {}
    return [serialize.project_summary(p, costs.get(p.id), scenes.get(p.id, 0)) for p in projects]


@router.post("", status_code=201)
def create_project(body: ProjectIn, db: Session = Depends(get_db)) -> dict:
    channel = get_or_404(db, Channel, body.channel_id, "Canal")
    p = Project(channel_id=channel.id, title=body.title.strip(), quality=(body.quality or Quality(channel.default_quality)).value,
                script=body.script, notes=body.notes, target_minutes=body.target_minutes,
                script_updated_at=utcnow() if body.script else None, status="script" if body.script.strip() else "draft")
    db.add(p)
    db.commit()
    return serialize.project_summary(p, 0.0, 0)


def stage_summary(db: Session, p: Project, scenes: list[dict], assets: dict[int, Asset]) -> dict:
    script_hash = text.content_hash(p.script or "")
    n = len(scenes)
    exports = sorted((a for a in assets.values() if a.kind == AssetKind.EXPORT.value), key=lambda a: a.id, reverse=True)
    thumbs = [a for a in assets.values() if a.kind == AssetKind.THUMBNAIL.value]
    narration = [a for a in assets.values() if a.kind == AssetKind.NARRATION.value]
    newest_asset = max((a.created_at for a in assets.values() if a.kind != AssetKind.EXPORT.value), default=None)
    ai = (p.analysis or {}).get("ai") or {}
    return {
        "script": {"words": text.word_count(p.script or ""), "ready": text.word_count(p.script or "") >= 30,
                   "analyzed": bool(p.analysis), "analysis_fresh": bool(p.analysis) and p.analysis_script_hash == script_hash,
                   "verdict": ai.get("verdict")},
        "scenes": {"count": n, "fresh": bool(n) and p.scenes_script_hash == script_hash,
                   "video": sum(1 for s in scenes if s["asset_type"] == "VIDEO"),
                   "duration": round(sum(s["duration"] for s in scenes), 2)},
        "visuals": {"ready": sum(1 for s in scenes if s["visual_ready"]), "total": n},
        "narration": {"ready": sum(1 for s in scenes if s["audio_ok"]), "total": n,
                      "duration": round(sum(s["audio_duration"] or 0 for s in scenes), 2),
                      "full": serialize.asset(max(narration, key=lambda a: a.id)) if narration else None},
        "thumbnail": {"concepts": len(p.concepts), "images": len(thumbs),
                      "selected": any(c.selected_asset_id for c in p.concepts)},
        "metadata": {"ready": bool(p.metadata_suggestions), "title": p.selected_title},
        "export": {"count": len(exports), "last": serialize.asset(exports[0]) if exports else None,
                   "outdated": bool(exports and newest_asset and newest_asset > exports[0].created_at)},
    }


@router.get("/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db)) -> dict:
    p = _project(db, project_id)
    channel = p.channel
    assets = serialize.attach_assets(db, p)
    try:
        tts = tts_settings(db, channel, p.quality)
    except StageError:
        tts = None
    scenes = [serialize.scene(s, visual_style=channel.visual_style, tts=tts, start=start)
              for s, start, _ in scene_timeline(list(p.scenes))]
    cost = usage_ledger.totals(db, UsageRecord.project_id == p.id)
    jobs = [serialize.job(j) for j in queue.active_for(db, project_id=p.id)]
    return {
        **serialize.project_summary(p, cost["cost"], len(scenes)),
        "script": p.script, "notes": p.notes, "target_minutes": p.target_minutes, "analysis": p.analysis,
        "analysis_at": serialize.iso(p.analysis_at), "metadata_suggestions": p.metadata_suggestions,
        "description": p.description, "tags": p.tags or [],
        "channel": serialize.channel(channel),
        "scenes_list": scenes,
        "concepts": [serialize.concept(c, assets) for c in sorted(p.concepts, key=lambda c: -c.position)],
        "stages": stage_summary(db, p, scenes, assets),
        "tts": tts,
        "active_jobs": jobs,
        "costs": cost,
    }


@router.patch("/{project_id}")
def update_project(project_id: int, body: ProjectPatch, db: Session = Depends(get_db)) -> dict:
    p = _project(db, project_id)
    data = body.model_dump(exclude_unset=True)
    if "script" in data and data["script"] is not None and data["script"] != p.script:
        p.script = data.pop("script")
        p.script_updated_at = utcnow()
        if p.status == "draft" and p.script.strip():
            p.status = "script"
    data.pop("script", None)
    if "quality" in data and data["quality"] is not None:
        data["quality"] = data["quality"].value
    if "selected_title" in data and data["selected_title"] is not None and data["selected_title"] != p.selected_title:
        options = [t.get("title") for t in ((p.metadata_suggestions or {}).get("titles") or [])]
        db.add(FeedbackEvent(channel_id=p.channel_id, project_id=p.id, kind="title_selected",
                             data={"title": data["selected_title"], "options": options[:8]}))
    if "description" in data and data["description"] is not None and data["description"] != p.description and p.description:
        db.add(FeedbackEvent(channel_id=p.channel_id, project_id=p.id, kind="description_edited",
                             data={"before": p.description[:600], "after": data["description"][:600]}))
    if "target_minutes" in data and not data["target_minutes"]:
        data["target_minutes"] = None
    for k, v in data.items():
        if v is not None or k == "target_minutes":
            setattr(p, k, v)
    db.commit()
    return get_project(project_id, db)


@router.delete("/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)) -> dict:
    p = _project(db, project_id)
    for job in queue.active_for(db, project_id=p.id):
        queue.cancel(db, job)
    get_storage().delete_tree(f"projects/{p.id}")
    db.delete(p)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ ações (jobs)


@router.post("/{project_id}/analyze")
def analyze(project_id: int, db: Session = Depends(get_db)) -> dict:
    p = _project(db, project_id)
    if text.word_count(p.script or "") < 30:
        raise HTTPException(400, "Escreva ou cole o roteiro (mínimo de 30 palavras).")
    job = queue.enqueue(db, "script.analyze", label=f"Análise do roteiro — {p.title[:60]}", project_id=p.id,
                        channel_id=p.channel_id)
    db.commit()
    return _job_out(job, "")


@router.post("/{project_id}/scenes/plan")
def plan(project_id: int, body: PlanIn, db: Session = Depends(get_db)) -> dict:
    p = _project(db, project_id)
    if len(text.segment_script(p.script or "")) < 3:
        raise HTTPException(400, "O roteiro precisa ter pelo menos 3 frases.")
    if p.scenes and not body.replace:
        raise HTTPException(409, "O projeto já tem cenas. Confirme para substituir (os assets das cenas serão apagados).")
    job = queue.enqueue(db, "scenes.plan", label=f"Divisão em cenas — {p.title[:60]}", project_id=p.id,
                        channel_id=p.channel_id, payload={"replace": body.replace})
    db.commit()
    return _job_out(job, "")


@router.post("/{project_id}/visuals")
def visuals(project_id: int, body: ScopeIn, db: Session = Depends(get_db)) -> dict:
    p = _project(db, project_id)
    if not p.scenes:
        raise HTTPException(400, "Crie as cenas antes de gerar imagens e vídeos.")
    serialize.attach_assets(db, p)
    group = enqueue_project_visuals(db, p, scope=body.scope, scene_ids=body.scene_ids)
    if group is not None and p.status in ("draft", "script", "scenes"):
        p.status = "production"
    db.commit()
    return _job_out(group, "Todas as cenas já têm visuais atualizados.")


@router.post("/{project_id}/narration")
def narration(project_id: int, body: ScopeIn, db: Session = Depends(get_db)) -> dict:
    p = _project(db, project_id)
    if not p.scenes:
        raise HTTPException(400, "Crie as cenas antes de gerar a narração.")
    try:
        group = enqueue_project_narration(db, p, scope=body.scope, scene_ids=body.scene_ids)
    except StageError as exc:
        raise HTTPException(400, str(exc)) from exc
    if group is not None and p.status in ("draft", "script", "scenes"):
        p.status = "production"
    db.commit()
    return _job_out(group, "Todas as cenas já têm narração atualizada.")


@router.post("/{project_id}/narration/merge")
def merge(project_id: int, body: MergeIn, db: Session = Depends(get_db)) -> dict:
    p = _project(db, project_id)
    job = queue.enqueue(db, "narration.merge", label=f"Narração completa — {p.title[:60]}", project_id=p.id,
                        channel_id=p.channel_id, payload={"gap": body.gap})
    db.commit()
    return _job_out(job, "")


@router.post("/{project_id}/thumbnails")
def thumbnails(project_id: int, body: ThumbIn, db: Session = Depends(get_db)) -> dict:
    p = _project(db, project_id)
    if not (p.script or "").strip():
        raise HTTPException(400, "Escreva o roteiro antes de criar thumbnails.")
    group = queue.create_group(db, "thumbnail.batch", label=f"Thumbnails — {p.title[:60]}", stage="thumbnail",
                               project_id=p.id, channel_id=p.channel_id)
    queue.enqueue(db, "thumbnail.concepts", label="Conceitos de thumbnail", project_id=p.id, channel_id=p.channel_id,
                  parent_id=group.id, payload=body.model_dump(exclude_none=True), dedupe=False)
    db.commit()
    return _job_out(group, "")


@router.post("/{project_id}/metadata")
def metadata(project_id: int, db: Session = Depends(get_db)) -> dict:
    p = _project(db, project_id)
    if not (p.script or "").strip():
        raise HTTPException(400, "Escreva o roteiro antes de gerar título e descrição.")
    job = queue.enqueue(db, "metadata.generate", label=f"Título e descrição — {p.title[:60]}", project_id=p.id,
                        channel_id=p.channel_id)
    db.commit()
    return _job_out(job, "")


@router.post("/{project_id}/export")
def export(project_id: int, body: ExportIn, db: Session = Depends(get_db)) -> dict:
    p = _project(db, project_id)
    job = queue.enqueue(db, "export.zip", label=f"Exportação — {p.title[:60]}", project_id=p.id,
                        channel_id=p.channel_id, payload=body.model_dump())
    db.commit()
    return _job_out(job, "")


@router.post("/{project_id}/learn")
def learn(project_id: int, db: Session = Depends(get_db)) -> dict:
    p = _project(db, project_id)
    job = queue.enqueue(db, "skill.learn", label=f"Aprendizados de '{p.title[:60]}'", project_id=p.id,
                        channel_id=p.channel_id)
    db.commit()
    return _job_out(job, "")


# ------------------------------------------------------------------ custos, jobs, exports


@router.get("/{project_id}/estimate")
def estimate(project_id: int, db: Session = Depends(get_db)) -> dict:
    p = _project(db, project_id)
    return estimate_project(db, p)


@router.get("/{project_id}/costs")
def costs(project_id: int, db: Session = Depends(get_db)) -> dict:
    p = _project(db, project_id)
    return usage_ledger.project_costs(db, p.id)


@router.get("/{project_id}/jobs")
def project_jobs(project_id: int, active: bool = False, limit: int = 50, db: Session = Depends(get_db)) -> list[dict]:
    _project(db, project_id)
    q = select(Job).where(Job.project_id == project_id, Job.parent_id.is_(None))
    if active:
        q = q.where(Job.status.in_(queue.ACTIVE))
    return [serialize.job(j) for j in db.scalars(q.order_by(Job.id.desc()).limit(min(limit, 200)))]


@router.get("/{project_id}/exports")
def exports(project_id: int, db: Session = Depends(get_db)) -> list[dict]:
    _project(db, project_id)
    rows = db.scalars(select(Asset).where(Asset.project_id == project_id, Asset.kind == AssetKind.EXPORT.value)
                      .order_by(Asset.id.desc()))
    return [serialize.asset(a) for a in rows]
