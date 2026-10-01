"""Etapa — vídeo final: junta visuais + narração + transições + texto na tela + efeitos sonoros (ffmpeg, sem IA).

Dispara sozinho quando o lote de narração (ou de visuais) termina e todas as cenas estão prontas;
também pode ser pedido a qualquer momento pela tela "Vídeo final".
"""

from __future__ import annotations

import logging
import shutil

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import montage
from ..config import get_settings
from ..db import session_scope
from ..jobs import queue
from ..jobs.context import JobContext, handler
from ..models import Asset, AssetKind, Job, Project
from ..providers.base import CanceledError
from ..storage import get_storage
from . import text
from .common import StageError, audio_hash, load_project, new_asset_path, tts_settings
from .estimate import planned
from .export import slugify
from .narration import scene_audio_state
from .visuals import scene_visual_state

log = logging.getLogger(__name__)

RENDER_VERSION = 1


def _tts(db: Session, project: Project) -> dict:
    return tts_settings(db, project.channel, project.quality, model=planned(project, "tts_model"))


def render_hash(project: Project) -> str:
    settings = get_settings()
    parts = [RENDER_VERSION, settings.motion_size, settings.motion_fps]
    for s in project.scenes:
        parts.append((s.id, s.image_asset_id, s.clip_asset_id, s.audio_asset_id, s.asset_type, s.motion,
                      s.transition, s.sfx, s.overlay_text))
    return text.content_hash(*parts)


def render_state(db: Session, project: Project) -> dict:
    """O que falta para o vídeo final e se o último vídeo montado ainda corresponde às cenas."""
    scenes = list(project.scenes)
    style = project.channel.visual_style
    tts = _tts(db, project) if scenes else None
    no_image = [s.position for s in scenes if not scene_visual_state(db, s, style)["image_ok"]]
    not_ready = [s.position for s in scenes if not scene_visual_state(db, s, style)["ready"]]
    no_audio = [s.position for s in scenes if not (tts and scene_audio_state(db, s, tts)["ready"])]
    last = db.scalar(select(Asset).where(Asset.project_id == project.id, Asset.kind == AssetKind.FINAL.value)
                     .order_by(Asset.id.desc()).limit(1))
    active = db.scalar(select(Job.id).where(Job.project_id == project.id, Job.kind == "render.final",
                                            Job.status.in_(queue.ACTIVE)).limit(1))
    return {
        "scenes": len(scenes),
        "can_render": bool(scenes) and not no_image and not no_audio,
        "complete": bool(scenes) and not not_ready and not no_audio,
        "missing_images": no_image[:50],
        "missing_audio": no_audio[:50],
        "pending_clips": [p for p in not_ready if p not in no_image][:50],
        "last": last,
        "outdated": bool(last and (last.params or {}).get("hash") != render_hash(project)),
        "running": active is not None,
    }


def enqueue_render(db: Session, project: Project, *, auto: bool = False) -> Job:
    label = f"Vídeo final — {project.title[:60]}" + (" (automático)" if auto else "")
    return queue.enqueue(db, "render.final", label=label, project_id=project.id, channel_id=project.channel_id,
                         payload={"auto": auto})


def _auto_render(db: Session, group: Job) -> None:
    """Ao terminar narração/visuais em lote: monta o vídeo se tudo estiver pronto e mudou algo."""
    if group.kind not in ("narration.batch", "visuals.batch") or not group.project_id:
        return
    project = db.get(Project, group.project_id)
    if project is None or not project.scenes:
        return
    state = render_state(db, project)
    if state["complete"] and not state["running"] and (state["last"] is None or state["outdated"]):
        enqueue_render(db, project, auto=True)


queue.GROUP_HOOKS.append(_auto_render)


@handler("render.final")
def render_final(ctx: JobContext) -> dict:
    storage = get_storage()
    settings = get_settings()
    width, height = settings.motion_dims()
    warnings: list[str] = []
    with session_scope() as db:
        project = load_project(db, ctx.project_id)
        scenes = list(project.scenes)
        if not scenes:
            raise StageError("Crie as cenas antes de montar o vídeo.")
        style = project.channel.visual_style
        tts = _tts(db, project)
        missing_audio, missing_image, shots = [], [], []
        for s in scenes:
            vis = scene_visual_state(db, s, style)
            audio = db.get(Asset, s.audio_asset_id) if s.audio_asset_id else None
            if audio is None:
                missing_audio.append(s.position)
                continue
            if audio.source_hash != audio_hash(s, tts):
                warnings.append(f"cena {s.position}: narração desatualizada (usada a última gerada)")
            image = vis["image"]
            if image is None:
                missing_image.append(s.position)
                continue
            clip = vis["clip"]
            kind = {"VIDEO": "video", "IMAGE": "still"}.get(s.asset_type, "motion")
            if kind == "video" and not (clip and clip.kind == AssetKind.VIDEO.value):
                warnings.append(f"cena {s.position}: sem vídeo IA pronto, usada a imagem com movimento")
                kind, clip = "motion", None
            if kind == "motion" and not (clip and clip.kind == AssetKind.MOTION.value and vis["clip_ok"]):
                clip = None  # movimento gerado na montagem
            shots.append(montage.Shot(
                duration=float(audio.duration or s.audio_duration or s.duration), audio=storage.path(audio.path),
                kind=kind, clip=storage.path(clip.path) if clip else None, image=storage.path(image.path),
                motion=s.motion, transition=s.transition, overlay=s.overlay_text, sfx=s.sfx,
            ))
        if missing_audio:
            raise StageError("Faltam narrações nas cenas: " + ", ".join(map(str, missing_audio[:30])))
        if missing_image:
            raise StageError("Faltam imagens nas cenas: " + ", ".join(map(str, missing_image[:30])))
        source_hash = render_hash(project)
        slug = slugify(project.selected_title or project.title)
    spec = montage.Spec(width=width, height=height, fps=settings.motion_fps, font=montage.find_font(),
                        warnings=warnings)
    if spec.font is None:
        warnings.append("nenhuma fonte instalada no servidor: vídeo sem texto na tela")
    work = storage.tmp_dir() / f"render-{ctx.job_id}"
    out = work / "final.mp4"
    try:
        try:
            info = montage.build(shots, out, spec, work / "parts", progress=lambda p, m: ctx.progress(p, m),
                                 canceled=ctx.canceled)
        except montage.Canceled as exc:
            raise CanceledError("cancelado pelo usuário") from exc
        ctx.progress(0.98, "salvando vídeo final", force=True)
        rel = new_asset_path(ctx.project_id, "final", slug, "mp4")
        size = storage.import_file(rel, out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    with session_scope() as db:
        # guarda só o vídeo final mais recente (cada um tem centenas de MB)
        for old in db.scalars(select(Asset).where(Asset.project_id == ctx.project_id,
                                                  Asset.kind == AssetKind.FINAL.value)):
            storage.delete(old.path)
            db.delete(old)
        asset = Asset(project_id=ctx.project_id, kind=AssetKind.FINAL.value, path=rel, mime="video/mp4",
                      size_bytes=size, provider="local", model="ffmpeg-montage", width=width, height=height,
                      duration=round(info["duration"], 3), job_id=ctx.job_id,
                      params={**info, "hash": source_hash, "fps": settings.motion_fps, "auto": ctx.payload.get("auto")})
        db.add(asset)
        db.flush()
        project = load_project(db, ctx.project_id)
        if project.status in ("draft", "script", "scenes", "production"):
            project.status = "ready"
        asset_id = asset.id
    mins = info["duration"] / 60
    extra = f" · {len(warnings)} aviso(s)" if warnings else ""
    return {"message": f"vídeo final pronto: {mins:.1f} min, {size / 1_048_576:.0f} MB{extra}", "asset_id": asset_id,
            "warnings": warnings}
