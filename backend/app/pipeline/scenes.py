"""Etapa 2 — transformar o roteiro em cenas (narração, duração, descrição visual, prompt, tipo de asset)."""

from __future__ import annotations

from sqlalchemy import select

from .. import tiers
from ..db import session_scope
from ..jobs.context import JobContext, handler
from ..models import Asset, FeedbackEvent, Scene, utcnow
from . import prompts, text
from .common import StageError, delete_asset_files, load_project, load_scene, model_for
from .context import full_context
from .llm import call_json
from .schemas import PlannedScene, ScenePlan, SceneRewrite

MAX_BLOCK_WORDS = 650


def normalize_plan(items: list[PlannedScene], first: int, last: int, segs: dict[int, text.Segment],
                   fallback_prompt: str) -> list[dict]:
    """Garante cobertura contínua [first..last]: sem buracos, sem sobreposição, em ordem."""
    ordered = sorted(items, key=lambda s: (s.start, s.end))
    out: list[dict] = []
    expected = first
    for item in ordered:
        start = max(item.start, first)
        end = min(item.end, last)
        if end < expected or start > last:
            continue
        if start > expected and out:
            out[-1]["end"] = start - 1  # buraco: estende a cena anterior
        else:
            start = expected  # sobreposição (ou primeira cena): começa onde a anterior terminou
        if end < start:
            continue
        out.append({**item.model_dump(), "start": start, "end": end})
        expected = end + 1
    if expected <= last:
        missing = list(range(expected, last + 1))
        if out and len(missing) <= 2:
            out[-1]["end"] = last
        else:
            narration = " ".join(segs[i].text for i in missing)
            out.append({
                "start": expected, "end": last,
                "visual_description": "Cena gerada automaticamente (a IA não cobriu este trecho).",
                "prompt": f"{fallback_prompt}. Scene illustrating: {narration[:300]}",
                "asset_type": "IMAGE_MOTION",
                "asset_type_reason": "Trecho não coberto pelo planejamento; revise o prompt.",
                "motion": "zoom_in",
            })
    return out


@handler("scenes.plan")
def plan_scenes(ctx: JobContext) -> dict:
    with session_scope() as db:
        project = load_project(db, ctx.project_id)
        channel = project.channel
        segs = text.segment_script(project.script or "")
        if len(segs) < 3:
            raise StageError("O roteiro precisa ter pelo menos 3 frases para ser dividido em cenas.")
        tier = project.quality
        model = model_for(db, "text", tier)
        params = tiers.tier_params(db, tier)
        wpm = channel.words_per_minute or text.default_wpm(channel.language)
        scene_seconds = channel.scene_seconds or 7.0
        video_percent = int(round(float(params.get("video_share") or 0) * 100))
        context = full_context(db, project)
        visual_style = channel.visual_style
        script_hash = text.content_hash(project.script)
    by_index = {s.index: s for s in segs}
    chunks = text.chunk_segments(segs, MAX_BLOCK_WORDS)
    planned: list[dict] = []
    previous = ""
    for i, chunk in enumerate(chunks, start=1):
        ctx.progress(0.05 + 0.85 * (i - 1) / len(chunks), f"planejando cenas — bloco {i}/{len(chunks)}", force=True)
        first, last = chunk[0].index, chunk[-1].index
        system, user = prompts.scene_plan(
            context, chunk, first=first, last=last, scene_seconds=scene_seconds, wpm=wpm,
            video_percent=video_percent, visual_style=visual_style, previous=previous, block=i, blocks=len(chunks),
        )
        expected_scenes = max(1, round(sum(s.words for s in chunk) / max(1, scene_seconds * wpm / 60)))
        plan, _ = call_json(ctx, model=model, system=system, user=user, schema=ScenePlan, schema_name="scene_plan",
                            temperature=0.6, max_tokens=16000, reasoning=params.get("reasoning"),
                            output_units=expected_scenes)
        part = normalize_plan(plan.scenes, first, last, by_index, visual_style or "cinematic documentary frame")
        planned.extend(part)
        if part:
            previous = part[-1]["visual_description"]
    with session_scope() as db:
        project = load_project(db, ctx.project_id)
        old = list(project.scenes)
        if old:
            assets = list(db.scalars(select(Asset).where(Asset.scene_id.in_([s.id for s in old]))))
            delete_asset_files(db, assets)
            for s in old:
                db.delete(s)
            db.flush()
        for pos, item in enumerate(planned, start=1):
            narration = " ".join(by_index[i].text for i in range(item["start"], item["end"] + 1))
            db.add(Scene(
                project_id=project.id, position=pos, narration=narration,
                est_duration=text.estimate_seconds(narration, wpm),
                visual_description=item["visual_description"], prompt=item["prompt"],
                asset_type=item["asset_type"], ai_asset_type=item["asset_type"],
                asset_type_reason=item["asset_type_reason"], motion=item["motion"],
                sentence_start=item["start"], sentence_end=item["end"],
            ))
        project.scenes_planned_at = utcnow()
        project.scenes_script_hash = script_hash
        if project.status in ("draft", "script"):
            project.status = "scenes"
    videos = sum(1 for p in planned if p["asset_type"] == "VIDEO")
    return {"message": f"{len(planned)} cenas criadas ({videos} com vídeo IA)", "scenes": len(planned)}


@handler("scene.rewrite")
def rewrite_scene(ctx: JobContext) -> dict:
    instruction = str(ctx.payload.get("instruction") or "").strip()
    with session_scope() as db:
        scene = load_scene(db, ctx.scene_id)
        project = scene.project
        channel = project.channel
        tier = project.quality
        model = model_for(db, "text", tier)
        params = tiers.tier_params(db, tier)
        scenes = list(project.scenes)
        idx = next(i for i, s in enumerate(scenes) if s.id == scene.id)
        prev_desc = scenes[idx - 1].visual_description if idx > 0 else ""
        next_desc = scenes[idx + 1].visual_description if idx + 1 < len(scenes) else ""
        before = {"visual_description": scene.visual_description, "prompt": scene.prompt,
                  "asset_type": scene.asset_type, "narration": scene.narration}
        system, user = prompts.scene_rewrite(
            full_context(db, project), before, prev_desc, next_desc, instruction,
            int(round(float(params.get("video_share") or 0) * 100)), channel.visual_style,
        )
    ctx.progress(0.2, "reescrevendo cena", force=True)
    result, _ = call_json(ctx, model=model, system=system, user=user, schema=SceneRewrite,
                          schema_name="scene_rewrite", temperature=0.8, max_tokens=3000)
    with session_scope() as db:
        scene = load_scene(db, ctx.scene_id)
        scene.visual_description = result.visual_description
        scene.prompt = result.prompt
        scene.asset_type = result.asset_type
        scene.ai_asset_type = result.asset_type
        scene.asset_type_reason = result.asset_type_reason
        scene.motion = result.motion
        if instruction:
            db.add(FeedbackEvent(channel_id=scene.project.channel_id, project_id=scene.project_id, scene_id=scene.id,
                                 kind="scene_rewrite_instruction",
                                 data={"instruction": instruction, "before": before["prompt"], "after": result.prompt}))
    return {"message": f"cena {ctx.payload.get('position', '')} atualizada".replace("  ", " ")}
