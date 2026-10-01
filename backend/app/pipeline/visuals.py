"""Etapa 3 — imagens e vídeos das cenas (imagem → movimento local ou vídeo IA)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from .. import catalog, media, pricing, tiers
from ..config import get_settings
from ..db import session_scope
from ..jobs import queue
from ..jobs.context import JobContext, handler
from ..models import Asset, AssetKind, AssetType, Job, Project, Scene
from ..providers import registry
from ..storage import get_storage
from . import prompts
from .common import StageError, clip_hash, load_scene, model_for, new_asset_path, save_asset, visual_hash

IMAGE_W, IMAGE_H = 1920, 1080


def scene_visual_state(db: Session, scene: Scene, visual_style: str) -> dict:
    """Estado dos visuais de uma cena: pronto / desatualizado / faltando."""
    image = db.get(Asset, scene.image_asset_id) if scene.image_asset_id else None
    clip = db.get(Asset, scene.clip_asset_id) if scene.clip_asset_id else None
    image_ok = bool(image and image.source_hash == visual_hash(scene, visual_style))
    clip_ok = False
    if scene.asset_type == AssetType.VIDEO.value:
        clip_ok = bool(clip and clip.kind == AssetKind.VIDEO.value and clip.source_hash == clip_hash(scene, visual_style))
    elif scene.asset_type == AssetType.IMAGE_MOTION.value:
        clip_ok = bool(clip and clip.kind == AssetKind.MOTION.value and clip.source_hash == clip_hash(scene, visual_style))
    ready = image_ok and (scene.asset_type == AssetType.IMAGE.value or clip_ok)
    return {"image": image, "clip": clip, "image_ok": image_ok, "clip_ok": clip_ok, "ready": ready}


def enqueue_scene_visual(db: Session, scene: Scene, *, parent_id: int | None = None, force: bool = False) -> Job | None:
    """Agenda só o que falta: imagem (e depois movimento/vídeo) ou apenas o clipe."""
    project = scene.project
    state = scene_visual_state(db, scene, project.channel.visual_style)
    if state["ready"] and not force:
        return None
    common = dict(project_id=project.id, channel_id=project.channel_id, scene_id=scene.id, parent_id=parent_id)
    if state["image_ok"] and not force:
        kind = "visual.video" if scene.asset_type == AssetType.VIDEO.value else "visual.motion"
        return queue.enqueue(db, kind, label=f"Cena {scene.position}: {'vídeo IA' if kind == 'visual.video' else 'movimento'}",
                             **common)
    return queue.enqueue(db, "visual.image", label=f"Cena {scene.position}: imagem", **common)


def enqueue_project_visuals(db: Session, project: Project, *, scope: str = "missing",
                            scene_ids: list[int] | None = None) -> Job | None:
    scenes = [s for s in project.scenes if not scene_ids or s.id in scene_ids]
    if scope != "all":
        scenes = [s for s in scenes if not scene_visual_state(db, s, project.channel.visual_style)["ready"]]
    if not scenes:
        return None
    group = queue.create_group(db, "visuals.batch", label=f"Visuais de {len(scenes)} cenas", stage="visuals",
                               project_id=project.id, channel_id=project.channel_id)
    for s in scenes:
        enqueue_scene_visual(db, s, parent_id=group.id, force=scope == "all")
    queue.update_group(db, group.id)
    return group


@handler("visual.image")
def generate_image(ctx: JobContext) -> dict:
    with session_scope() as db:
        scene = load_scene(db, ctx.scene_id)
        project = scene.project
        channel = project.channel
        if not scene.prompt.strip():
            raise StageError(f"A cena {scene.position} está sem prompt visual.")
        tier = project.quality
        model = model_for(db, "image", tier)
        resolution = tiers.tier_params(db, tier).get("image_resolution")
        prompt = prompts.image_prompt(scene.prompt, channel.visual_style)
        source_hash = visual_hash(scene, channel.visual_style)
        position = scene.position
    ctx.progress(0.1, f"cena {position}: gerando imagem ({model})", force=True)
    provider, model_id = registry.split_ref(model)
    result = registry.image(provider).generate(model=model_id, prompt=prompt, aspect_ratio="16:9",
                                               resolution=resolution, session_id=f"dm-project-{ctx.project_id}")
    ctx.progress(0.8, "processando imagem")
    jpg = media.fit_cover(result.data, IMAGE_W, IMAGE_H)
    with session_scope() as db:
        scene = load_scene(db, ctx.scene_id)
        asset = save_asset(
            db, project_id=scene.project_id, scene_id=scene.id, kind=AssetKind.IMAGE.value, data=jpg,
            path=new_asset_path(scene.project_id, f"scenes/{scene.id}", "image", "jpg"), mime="image/jpeg",
            usage=result.usage, prompt=prompt, params={**result.meta.get("params", {}), "resolution": resolution},
            source_hash=source_hash, job_id=ctx.job_id, width=IMAGE_W, height=IMAGE_H,
        )
        ctx.record(db, result.usage, scene_id=scene.id, meta={"resolution": resolution, "asset_id": asset.id})
        scene.image_asset_id = asset.id
        follow = None
        if ctx.payload.get("chain", True):
            if scene.asset_type == AssetType.IMAGE_MOTION.value:
                follow = ctx.follow_up(db, "visual.motion", scene_id=scene.id, label=f"Cena {scene.position}: movimento")
            elif scene.asset_type == AssetType.VIDEO.value:
                follow = ctx.follow_up(db, "visual.video", scene_id=scene.id, label=f"Cena {scene.position}: vídeo IA")
    cost = f" · US$ {result.usage.cost_usd:.4f}" if result.usage.cost_usd is not None else ""
    return {"message": f"imagem da cena {position} pronta{cost}", "asset_id": asset.id,
            "next": follow.kind if follow else None}


def _scene_image(db: Session, scene: Scene) -> bytes:
    asset = db.get(Asset, scene.image_asset_id) if scene.image_asset_id else None
    if asset is None:
        raise StageError(f"A cena {scene.position} ainda não tem imagem.")
    return get_storage().read_bytes(asset.path)


@handler("visual.motion")
def render_motion(ctx: JobContext) -> dict:
    with session_scope() as db:
        scene = load_scene(db, ctx.scene_id)
        image = _scene_image(db, scene)
        duration = max(2.0, scene.duration)
        motion = scene.motion if scene.asset_type == AssetType.IMAGE_MOTION.value else "static"
        source_hash = clip_hash(scene, scene.project.channel.visual_style)
        position = scene.position
    ctx.progress(0.2, f"cena {position}: renderizando movimento ({motion}, {duration:.1f}s)", force=True)
    settings = get_settings()
    width, height = settings.motion_dims()
    result = registry.motion().render(image, duration, motion, width=width, height=height, fps=settings.motion_fps)
    with session_scope() as db:
        scene = load_scene(db, ctx.scene_id)
        asset = save_asset(
            db, project_id=scene.project_id, scene_id=scene.id, kind=AssetKind.MOTION.value, data=result.data,
            path=new_asset_path(scene.project_id, f"scenes/{scene.id}", "motion", "mp4"), mime="video/mp4",
            usage=result.usage, params=result.meta.get("params", {}), source_hash=source_hash, job_id=ctx.job_id,
            width=width, height=height, duration=round(duration, 3),
        )
        ctx.record(db, result.usage, scene_id=scene.id)
        scene.clip_asset_id = asset.id
    return {"message": f"movimento da cena {position} pronto (sem custo)", "asset_id": asset.id}


@handler("visual.video")
def generate_video(ctx: JobContext) -> dict:
    with session_scope() as db:
        scene = load_scene(db, ctx.scene_id)
        project = scene.project
        channel = project.channel
        tier = project.quality
        model = model_for(db, "video", tier)
        provider, model_id = registry.split_ref(model)
        info = catalog.video_model(model_id) if provider == "openrouter" else None
        duration = pricing.video_duration_for(info, scene.duration)
        resolution = pricing.video_resolution_for(info, tiers.tier_params(db, tier).get("video_resolution") or "720p")
        first_frame = _scene_image(db, scene) if scene.image_asset_id else None
        prompt = prompts.video_prompt(scene.prompt, scene.motion, channel.visual_style)
        source_hash = clip_hash(scene, channel.visual_style)
        position = scene.position
    ctx.progress(0.05, f"cena {position}: enviando vídeo ({model_id}, {duration}s, {resolution})", force=True)
    result = registry.video(provider).generate(
        model=model_id, prompt=prompt, duration=duration, resolution=resolution, aspect_ratio="16:9",
        first_frame=first_frame, progress=lambda p, m: ctx.progress(p, f"cena {position}: {m}"),
        canceled=ctx.canceled, session_id=f"dm-project-{ctx.project_id}",
    )
    tmp = get_storage().tmp_dir() / f"video-{ctx.job_id}.mp4"
    tmp.write_bytes(result.data)
    try:
        info_probe = media.probe(tmp)
    finally:
        tmp.unlink(missing_ok=True)
    with session_scope() as db:
        scene = load_scene(db, ctx.scene_id)
        asset = save_asset(
            db, project_id=scene.project_id, scene_id=scene.id, kind=AssetKind.VIDEO.value, data=result.data,
            path=new_asset_path(scene.project_id, f"scenes/{scene.id}", "video", "mp4"), mime="video/mp4",
            usage=result.usage, prompt=prompt, params={**result.meta.get("params", {}),
                                                       "first_frame": result.meta.get("first_frame")},
            source_hash=source_hash, job_id=ctx.job_id, width=info_probe.get("width"),
            height=info_probe.get("height"), duration=info_probe.get("duration"),
        )
        ctx.record(db, result.usage, scene_id=scene.id, meta={"resolution": resolution, "asset_id": asset.id})
        scene.clip_asset_id = asset.id
    cost = f" · US$ {result.usage.cost_usd:.4f}" if result.usage.cost_usd is not None else ""
    return {"message": f"vídeo da cena {position} pronto{cost}", "asset_id": asset.id}
