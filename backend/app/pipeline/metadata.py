"""Etapa 6 — título, descrição, capítulos, tags e palavras-chave."""

from __future__ import annotations

from ..db import session_scope
from ..jobs.context import JobContext, handler
from .. import tiers
from . import prompts, text
from .common import StageError, load_project, model_for, scene_timeline
from .context import full_context
from .llm import call_json
from .schemas import VideoMetadata


def build_chapters(chapters: list, timeline: list) -> list[dict]:
    """Capítulos com horário real: começa em 0:00, ordem crescente, mínimo de 10 s entre eles."""
    starts = {s.position: start for s, start, _ in timeline}
    total = timeline[-1][1] + timeline[-1][2] if timeline else 0
    out: list[dict] = []
    for ch in sorted(chapters, key=lambda c: c.scene):
        t = 0.0 if not out else starts.get(ch.scene)
        if t is None or (out and t - out[-1]["seconds"] < 10) or (total and total - t < 10):
            continue
        out.append({"seconds": round(t, 2), "time": text.timecode(t), "title": ch.title.strip()[:60], "scene": ch.scene})
    return out if len(out) >= 3 else []


def trim_tags(tags: list[str], limit: int = 480) -> list[str]:
    out, total, seen = [], 0, set()
    for tag in tags:
        t = tag.strip().lstrip("#").strip()
        if not t or t.lower() in seen:
            continue
        cost = len(t) + (2 if " " in t else 0) + 1
        if total + cost > limit:
            break
        out.append(t)
        seen.add(t.lower())
        total += cost
    return out


def compose_description(body: str, chapters: list[dict], hashtags: list[str]) -> str:
    parts = [body.strip()]
    if chapters:
        parts.append("\n".join(f"{c['time']} {c['title']}" for c in chapters))
    tags = " ".join(h if h.startswith("#") else f"#{h}" for h in hashtags[:3])
    if tags:
        parts.append(tags)
    return "\n\n".join(p for p in parts if p)


@handler("metadata.generate")
def generate_metadata(ctx: JobContext) -> dict:
    with session_scope() as db:
        project = load_project(db, ctx.project_id)
        channel = project.channel
        if not (project.script or "").strip():
            raise StageError("Escreva o roteiro antes de gerar título e descrição.")
        tier = project.quality
        model = model_for(db, "text", tier)
        timeline = scene_timeline(list(project.scenes))
        outline = "\n".join(
            f"{s.position} · {text.timecode(start)} · {' '.join(s.narration.split()[:12])}…"
            for s, start, _ in timeline
        ) or "(scenes not planned yet — choose chapters by script order; use scene 1)"
        overlay = ""
        for c in project.concepts:
            if c.selected_asset_id:
                overlay = c.overlay_text
        system, user = prompts.metadata(full_context(db, project), project.script, outline,
                                        text.language_label(channel.language), overlay)
        reasoning = tiers.tier_params(db, tier).get("reasoning")
    ctx.progress(0.2, "gerando títulos, descrição e tags", force=True)
    result, llm = call_json(ctx, model=model, system=system, user=user, schema=VideoMetadata,
                            schema_name="video_metadata", temperature=0.7, max_tokens=8000, reasoning=reasoning)
    with session_scope() as db:
        project = load_project(db, ctx.project_id)
        timeline = scene_timeline(list(project.scenes))
        chapters = build_chapters(result.chapters, timeline) if timeline else []
        tags = trim_tags(result.tags)
        hashtags = [h if h.startswith("#") else f"#{h}" for h in result.hashtags[:3]]
        description = compose_description(result.description, chapters, hashtags)
        suggestions = {
            "titles": [t.model_dump() for t in result.titles],
            "description_body": result.description,
            "description": description,
            "chapters": chapters,
            "tags": tags,
            "hashtags": hashtags,
            "primary_keywords": result.primary_keywords,
            "secondary_keywords": result.secondary_keywords,
            "policy_notes": result.policy_notes,
            "model": llm.model,
            "timeline_source": "audio" if all(s.audio_duration for s in project.scenes) and project.scenes else "estimate",
        }
        project.metadata_suggestions = suggestions
        if not project.selected_title and result.titles:
            project.selected_title = result.titles[0].title[:300]
        if not project.description.strip():
            project.description = description
        if not project.tags:
            project.tags = tags
    return {"message": f"{len(result.titles)} títulos, descrição e {len(tags)} tags gerados"}
