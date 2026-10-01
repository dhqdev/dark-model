from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import serialize
from ..deps import get_db, get_or_404, require_user
from ..jobs import queue
from ..models import Asset, AssetKind, AssetType, FeedbackEvent, Motion, Scene
from ..pipeline import text
from ..pipeline.common import StageError, delete_asset_files, tts_settings
from ..pipeline.estimate import planned
from ..pipeline.schemas import clean_overlay, norm_sfx, norm_transition
from ..pipeline.narration import enqueue_scene_narration
from ..pipeline.visuals import enqueue_scene_visual

router = APIRouter(prefix="/scenes", tags=["scenes"], dependencies=[Depends(require_user)])


class ScenePatch(BaseModel):
    narration: str | None = None
    visual_description: str | None = None
    prompt: str | None = None
    asset_type: AssetType | None = None
    motion: Motion | None = None
    locked: bool | None = None
    notes: str | None = None
    transition: str | None = None
    sfx: str | None = None
    overlay_text: str | None = Field(None, max_length=120)


class RewriteIn(BaseModel):
    instruction: str = Field("", max_length=1000)


class VisualIn(BaseModel):
    force: bool = False
    step: str = Field("auto", pattern="^(auto|image|clip)$")


class SelectIn(BaseModel):
    asset_id: int


def _scene(db: Session, scene_id: int) -> Scene:
    return get_or_404(db, Scene, scene_id, "Cena")


def _out(db: Session, s: Scene) -> dict:
    p = s.project
    serialize.attach_assets(db, p)
    try:
        tts = tts_settings(db, p.channel, p.quality, model=planned(p, "tts_model"))
    except StageError:
        tts = None
    return serialize.scene(s, visual_style=p.channel.visual_style, tts=tts)


@router.patch("/{scene_id}")
def update_scene(scene_id: int, body: ScenePatch, db: Session = Depends(get_db)) -> dict:
    s = _scene(db, scene_id)
    p = s.project
    data = body.model_dump(exclude_unset=True)
    if data.get("transition") is not None:
        data["transition"] = norm_transition(data["transition"])
    if data.get("sfx") is not None:
        data["sfx"] = norm_sfx(data["sfx"])
    if data.get("overlay_text") is not None:
        data["overlay_text"] = clean_overlay(data["overlay_text"])
    events = []
    if data.get("prompt") is not None and data["prompt"].strip() != s.prompt.strip():
        events.append(("scene_prompt_edited", {"before": s.prompt, "after": data["prompt"], "position": s.position}))
    if data.get("asset_type") is not None and data["asset_type"].value != s.asset_type:
        events.append(("scene_asset_type_changed", {"before": s.asset_type, "after": data["asset_type"].value,
                                                    "ai": s.ai_asset_type, "narration": s.narration[:200]}))
    if data.get("narration") is not None and data["narration"].strip() != s.narration.strip():
        events.append(("narration_edited", {"before": s.narration, "after": data["narration"]}))
        wpm = p.channel.words_per_minute or text.default_wpm(p.channel.language)
        s.est_duration = text.estimate_seconds(data["narration"], wpm)
    for k, v in data.items():
        if v is None:
            continue
        setattr(s, k, v.value if hasattr(v, "value") else v)
    for kind, payload in events:
        db.add(FeedbackEvent(channel_id=p.channel_id, project_id=p.id, scene_id=s.id, kind=kind, data=payload))
    db.commit()
    return _out(db, s)


@router.delete("/{scene_id}")
def delete_scene(scene_id: int, db: Session = Depends(get_db)) -> dict:
    s = _scene(db, scene_id)
    p = s.project
    delete_asset_files(db, list(db.scalars(select(Asset).where(Asset.scene_id == s.id))))
    db.delete(s)
    db.flush()
    for i, other in enumerate(sorted((x for x in p.scenes if x.id != scene_id), key=lambda x: x.position), start=1):
        other.position = i
    db.commit()
    return {"ok": True}


@router.post("/{scene_id}/rewrite")
def rewrite(scene_id: int, body: RewriteIn, db: Session = Depends(get_db)) -> dict:
    s = _scene(db, scene_id)
    job = queue.enqueue(db, "scene.rewrite", label=f"Cena {s.position}: nova proposta visual",
                        project_id=s.project_id, channel_id=s.project.channel_id, scene_id=s.id,
                        payload={"instruction": body.instruction, "position": s.position})
    db.commit()
    return {"job": serialize.job(job)}


@router.post("/{scene_id}/visual")
def visual(scene_id: int, body: VisualIn, db: Session = Depends(get_db)) -> dict:
    s = _scene(db, scene_id)
    p = s.project
    serialize.attach_assets(db, p)
    if body.step == "clip":
        if s.asset_type == AssetType.IMAGE.value:
            raise HTTPException(400, "Cenas do tipo IMAGEM não têm clipe; mude para IMAGEM + MOVIMENTO ou VÍDEO.")
        if not s.image_asset_id:
            raise HTTPException(400, "Gere a imagem da cena primeiro.")
        kind = "visual.video" if s.asset_type == AssetType.VIDEO.value else "visual.motion"
        job = queue.enqueue(db, kind, label=f"Cena {s.position}: {'vídeo IA' if kind == 'visual.video' else 'movimento'}",
                            project_id=p.id, channel_id=p.channel_id, scene_id=s.id)
    elif body.step == "image":
        job = queue.enqueue(db, "visual.image", label=f"Cena {s.position}: imagem", project_id=p.id,
                            channel_id=p.channel_id, scene_id=s.id)
    else:
        job = enqueue_scene_visual(db, s, force=body.force)
    db.commit()
    return {"job": serialize.job(job) if job else None,
            "message": "" if job else "Visual da cena já está atualizado (use 'regenerar' para forçar)."}


@router.post("/{scene_id}/narration")
def narration(scene_id: int, db: Session = Depends(get_db)) -> dict:
    s = _scene(db, scene_id)
    if not s.narration.strip():
        raise HTTPException(400, "A cena não tem texto de narração.")
    job = enqueue_scene_narration(db, s)
    db.commit()
    return {"job": serialize.job(job)}


@router.get("/{scene_id}/assets")
def scene_assets(scene_id: int, db: Session = Depends(get_db)) -> list[dict]:
    _scene(db, scene_id)
    rows = db.scalars(select(Asset).where(Asset.scene_id == scene_id).order_by(Asset.id.desc()))
    return [serialize.asset(a) for a in rows]


@router.post("/{scene_id}/select")
def select_asset(scene_id: int, body: SelectIn, db: Session = Depends(get_db)) -> dict:
    s = _scene(db, scene_id)
    a = get_or_404(db, Asset, body.asset_id, "Asset")
    if a.scene_id != s.id:
        raise HTTPException(400, "Este arquivo não pertence à cena.")
    if a.kind == AssetKind.IMAGE.value:
        s.image_asset_id = a.id
    elif a.kind in (AssetKind.MOTION.value, AssetKind.VIDEO.value):
        s.clip_asset_id = a.id
    elif a.kind == AssetKind.AUDIO.value:
        s.audio_asset_id = a.id
        s.audio_duration = a.duration
    db.add(FeedbackEvent(channel_id=s.project.channel_id, project_id=s.project_id, scene_id=s.id,
                         kind="asset_version_selected", data={"kind": a.kind, "asset_id": a.id}))
    db.commit()
    return _out(db, s)
