"""Conversão dos modelos em JSON para o frontend."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    Asset, AssetKind, AssetType, Channel, Job, Project, Scene, Skill, SkillLearning, ThumbnailConcept, UsageRecord,
)
from .pipeline import text
from .pipeline.common import audio_hash, clip_hash, visual_hash


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def asset(a: Asset | None) -> dict[str, Any] | None:
    if a is None:
        return None
    return {
        "id": a.id, "kind": a.kind, "url": f"/api/assets/{a.id}/file", "mime": a.mime, "size": a.size_bytes,
        "width": a.width, "height": a.height, "duration": a.duration, "provider": a.provider, "model": a.model,
        "cost": a.cost_usd, "prompt": a.prompt, "params": a.params or {}, "scene_id": a.scene_id,
        "concept_id": a.concept_id, "created_at": iso(a.created_at),
    }


def channel(c: Channel, stats: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": c.id, "name": c.name, "slug": c.slug, "language": c.language, "country": c.country,
        "audience": c.audience, "niche": c.niche, "style": c.style, "tone": c.tone,
        "duration_min": c.duration_min, "duration_max": c.duration_max,
        "words_per_minute": c.words_per_minute, "default_wpm": text.default_wpm(c.language),
        "scene_seconds": c.scene_seconds, "visual_style": c.visual_style, "default_quality": c.default_quality,
        "tts_model": c.tts_model, "tts_voice": c.tts_voice, "tts_speed": c.tts_speed, "tts_style": c.tts_style,
        "thumbnail_style": c.thumbnail_style, "thumbnail_text_mode": c.thumbnail_text_mode,
        "auto_learn": c.auto_learn, "notes": c.notes, "archived": c.archived,
        "created_at": iso(c.created_at), "updated_at": iso(c.updated_at), "stats": stats or {},
    }


def channel_stats(db: Session, channel_ids: list[int] | None = None) -> dict[int, dict[str, Any]]:
    q_proj = select(Project.channel_id, func.count(Project.id)).where(Project.archived.is_(False)).group_by(Project.channel_id)
    q_cost = select(UsageRecord.channel_id, func.coalesce(func.sum(UsageRecord.cost_usd), 0.0)).group_by(UsageRecord.channel_id)
    q_skill = select(Skill.channel_id, func.max(Skill.version)).group_by(Skill.channel_id)
    q_learn = (select(SkillLearning.channel_id, func.count(SkillLearning.id))
               .where(SkillLearning.status == "proposed").group_by(SkillLearning.channel_id))
    out: dict[int, dict[str, Any]] = {}
    for cid, n in db.execute(q_proj):
        out.setdefault(cid, {})["projects"] = n
    for cid, cost in db.execute(q_cost):
        if cid is not None:
            out.setdefault(cid, {})["cost"] = round(float(cost), 6)
    for cid, v in db.execute(q_skill):
        out.setdefault(cid, {})["skill_version"] = v
    for cid, n in db.execute(q_learn):
        out.setdefault(cid, {})["pending_learnings"] = n
    return out


def skill(s: Skill | None) -> dict[str, Any] | None:
    if s is None:
        return None
    return {"id": s.id, "version": s.version, "content": s.content, "note": s.note, "source": s.source,
            "created_at": iso(s.created_at)}


def learning(item: SkillLearning) -> dict[str, Any]:
    return {"id": item.id, "channel_id": item.channel_id, "project_id": item.project_id, "category": item.category,
            "text": item.text, "rationale": item.rationale, "status": item.status, "source": item.source,
            "created_at": iso(item.created_at), "decided_at": iso(item.decided_at)}


def job(j: Job) -> dict[str, Any]:
    return {
        "id": j.id, "kind": j.kind, "stage": j.stage, "lane": j.lane, "label": j.label, "status": j.status,
        "project_id": j.project_id, "channel_id": j.channel_id, "scene_id": j.scene_id, "target_id": j.target_id,
        "parent_id": j.parent_id, "is_group": j.is_group, "progress": round(j.progress or 0.0, 4),
        "message": j.message, "error": j.error, "attempts": j.attempts, "max_attempts": j.max_attempts,
        "cost": round(j.cost_usd or 0.0, 6), "result": j.result, "cancel_requested": j.cancel_requested,
        "created_at": iso(j.created_at), "started_at": iso(j.started_at), "finished_at": iso(j.finished_at),
        "run_after": iso(j.run_after),
    }


def scene(s: Scene, *, visual_style: str, tts: dict[str, Any] | None, start: float = 0.0) -> dict[str, Any]:
    image = s.__dict__.get("_image")
    clip = s.__dict__.get("_clip")
    audio = s.__dict__.get("_audio")
    image_ok = bool(image and image.source_hash == visual_hash(s, visual_style))
    wanted_clip = {AssetType.VIDEO.value: AssetKind.VIDEO.value, AssetType.IMAGE_MOTION.value: AssetKind.MOTION.value}
    clip_ok = bool(clip and clip.kind == wanted_clip.get(s.asset_type) and clip.source_hash == clip_hash(s, visual_style))
    visual_ready = image_ok and (s.asset_type == AssetType.IMAGE.value or clip_ok)
    audio_ok = bool(audio and tts and audio.source_hash == audio_hash(s, tts))
    return {
        "id": s.id, "position": s.position, "narration": s.narration, "est_duration": s.est_duration,
        "audio_duration": s.audio_duration, "duration": s.duration, "start": round(start, 3),
        "words": text.word_count(s.narration), "visual_description": s.visual_description, "prompt": s.prompt,
        "asset_type": s.asset_type, "ai_asset_type": s.ai_asset_type, "asset_type_reason": s.asset_type_reason,
        "motion": s.motion, "locked": s.locked, "notes": s.notes,
        "image": asset(image), "clip": asset(clip), "audio": asset(audio),
        "image_ok": image_ok, "clip_ok": clip_ok, "visual_ready": visual_ready, "audio_ok": audio_ok,
        "updated_at": iso(s.updated_at),
    }


def attach_assets(db: Session, project: Project) -> dict[int, Asset]:
    assets = {a.id: a for a in db.scalars(select(Asset).where(Asset.project_id == project.id))}
    for s in project.scenes:
        s.__dict__["_image"] = assets.get(s.image_asset_id)
        s.__dict__["_clip"] = assets.get(s.clip_asset_id)
        s.__dict__["_audio"] = assets.get(s.audio_asset_id)
    return assets


def concept(c: ThumbnailConcept, assets: dict[int, Asset]) -> dict[str, Any]:
    files = sorted((a for a in assets.values() if a.concept_id == c.id), key=lambda a: a.id)
    return {"id": c.id, "position": c.position, "name": c.name, "idea": c.idea, "emotion": c.emotion,
            "composition": c.composition, "overlay_text": c.overlay_text, "prompt": c.prompt, "rationale": c.rationale,
            "selected_asset_id": c.selected_asset_id, "images": [asset(a) for a in files],
            "created_at": iso(c.created_at)}


def project_summary(p: Project, cost: float | None = None, scenes: int | None = None) -> dict[str, Any]:
    return {
        "id": p.id, "channel_id": p.channel_id, "title": p.title, "status": p.status, "quality": p.quality,
        "selected_title": p.selected_title, "words": text.word_count(p.script or ""), "scenes": scenes,
        "cost": round(cost or 0.0, 6), "archived": p.archived, "created_at": iso(p.created_at),
        "updated_at": iso(p.updated_at),
    }
