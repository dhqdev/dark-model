"""Etapa 4 — narração por cena (TTS), com duração real medida e narração completa."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from .. import media
from ..db import session_scope
from ..jobs import queue
from ..jobs.context import JobContext, handler
from ..models import Asset, AssetKind, AssetType, Job, Project, Scene
from ..providers import registry
from ..storage import get_storage
from .common import StageError, audio_hash, clip_hash, load_project, load_scene, new_asset_path, save_asset, tts_settings
from .estimate import production_plan

MAX_CHARS = 3500


def split_for_tts(text: str, limit: int = MAX_CHARS) -> list[str]:
    text = text.strip()
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    cur = ""
    for sentence in re.split(r"(?<=[.!?…])\s+", text):
        if cur and len(cur) + len(sentence) + 1 > limit:
            parts.append(cur)
            cur = sentence
        else:
            cur = f"{cur} {sentence}".strip()
    if cur:
        parts.append(cur)
    return parts


def scene_audio_state(db: Session, scene: Scene, settings: dict) -> dict:
    audio = db.get(Asset, scene.audio_asset_id) if scene.audio_asset_id else None
    ok = bool(audio and audio.source_hash == audio_hash(scene, settings))
    return {"audio": audio, "ready": ok}


def enqueue_scene_narration(db: Session, scene: Scene, *, parent_id: int | None = None) -> Job:
    project = scene.project
    return queue.enqueue(db, "narration.scene", label=f"Cena {scene.position}: narração", project_id=project.id,
                         channel_id=project.channel_id, scene_id=scene.id, parent_id=parent_id)


def enqueue_project_narration(db: Session, project: Project, *, scope: str = "missing",
                              scene_ids: list[int] | None = None) -> Job | None:
    settings = tts_settings(db, project.channel, project.quality, model=production_plan(db, project).get("tts_model"))
    scenes = [s for s in project.scenes if not scene_ids or s.id in scene_ids]
    if scope != "all":
        scenes = [s for s in scenes if not scene_audio_state(db, s, settings)["ready"]]
    scenes = [s for s in scenes if s.narration.strip()]
    if not scenes:
        return None
    group = queue.create_group(db, "narration.batch", label=f"Narração de {len(scenes)} cenas", stage="narration",
                               project_id=project.id, channel_id=project.channel_id)
    for s in scenes:
        enqueue_scene_narration(db, s, parent_id=group.id)
    queue.update_group(db, group.id)
    return group


@handler("narration.scene")
def narrate_scene(ctx: JobContext) -> dict:
    with session_scope() as db:
        scene = load_scene(db, ctx.scene_id)
        project = scene.project
        if not scene.narration.strip():
            raise StageError(f"A cena {scene.position} não tem texto de narração.")
        settings = tts_settings(db, project.channel, project.quality,
                                model=production_plan(db, project).get("tts_model"))
        source_hash = audio_hash(scene, settings)
        text_parts = split_for_tts(scene.narration)
        position = scene.position
    provider, model_id = registry.split_ref(settings["model"])
    tts = registry.tts(provider)
    audio_parts: list[bytes] = []
    costs: list[float | None] = []
    for i, part in enumerate(text_parts, start=1):
        ctx.progress(0.1 + 0.7 * (i - 1) / len(text_parts), f"cena {position}: narrando ({settings['voice']})", force=True)
        res = tts.synthesize(model=model_id, text=part, voice=settings["voice"], speed=settings["speed"],
                             style=settings["style"] or None, session_id=f"dm-project-{ctx.project_id}")
        ctx.record_now(res.usage, scene_id=ctx.scene_id, meta={"voice": settings["voice"]})
        audio_parts.append(res.data)
        costs.append(res.usage.cost_usd)
    with tempfile.TemporaryDirectory() as tmp:
        files = []
        for i, data in enumerate(audio_parts):
            p = Path(tmp) / f"part{i}.mp3"
            p.write_bytes(data)
            files.append(p)
        final = Path(tmp) / "scene.mp3"
        if len(files) == 1:
            final = files[0]
        else:
            media.concat_audio(files, final)
        duration = media.probe_duration(final) or 0.0
        data = final.read_bytes()
    with session_scope() as db:
        scene = load_scene(db, ctx.scene_id)
        asset = save_asset(
            db, project_id=scene.project_id, scene_id=scene.id, kind=AssetKind.AUDIO.value, data=data,
            path=new_asset_path(scene.project_id, f"scenes/{scene.id}", "narration", "mp3"), mime="audio/mpeg",
            usage=res.usage if len(audio_parts) == 1 else None, prompt=scene.narration,
            params={"voice": settings["voice"], "speed": settings["speed"], "model": settings["model"]},
            source_hash=source_hash, job_id=ctx.job_id, duration=round(duration, 3),
        )
        if len(audio_parts) > 1:
            asset.provider, asset.model = provider, model_id
            asset.cost_usd = sum(c for c in costs if c is not None) if all(c is not None for c in costs) else None
        scene.audio_asset_id = asset.id
        scene.audio_duration = round(duration, 3)
        # movimento sincronizado com a duração real do áudio (re-render local, sem custo)
        clip = db.get(Asset, scene.clip_asset_id) if scene.clip_asset_id else None
        if (scene.asset_type == AssetType.IMAGE_MOTION.value and clip is not None and clip.kind == AssetKind.MOTION.value
                and clip.source_hash == clip_hash(scene, scene.project.channel.visual_style)
                and abs((clip.duration or 0) - duration) > 0.3):
            ctx.follow_up(db, "visual.motion", scene_id=scene.id, label=f"Cena {scene.position}: ajustar movimento ao áudio")
    note = f" ({settings['warning']})" if settings["warning"] else ""
    return {"message": f"narração da cena {position}: {duration:.1f}s{note}", "asset_id": asset.id}


@handler("narration.merge")
def merge_narration(ctx: JobContext) -> dict:
    gap = float(ctx.payload.get("gap", 0.0))
    with session_scope() as db:
        project = load_project(db, ctx.project_id)
        missing = [s.position for s in project.scenes if not s.audio_asset_id]
        if missing:
            raise StageError(f"Faltam narrações nas cenas: {', '.join(map(str, missing[:20]))}")
        storage = get_storage()
        paths = [storage.path(db.get(Asset, s.audio_asset_id).path) for s in project.scenes]
    ctx.progress(0.3, f"juntando {len(paths)} áudios", force=True)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "narration.mp3"
        media.concat_audio(paths, out, gap_seconds=gap)
        duration = media.probe_duration(out) or 0.0
        data = out.read_bytes()
    with session_scope() as db:
        asset = save_asset(db, project_id=ctx.project_id, kind=AssetKind.NARRATION.value, data=data,
                           path=new_asset_path(ctx.project_id, "narration", "narracao-completa", "mp3"),
                           mime="audio/mpeg", params={"gap": gap, "scenes": len(paths)}, job_id=ctx.job_id,
                           duration=round(duration, 3))
    return {"message": f"narração completa: {duration / 60:.1f} min", "asset_id": asset.id}
