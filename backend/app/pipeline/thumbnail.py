"""Etapa 5 — conceitos de thumbnail, prompts, imagens e variações."""

from __future__ import annotations

from .. import media, tiers
from ..db import session_scope
from ..jobs.context import JobContext, handler
from ..models import AssetKind, ThumbnailConcept
from ..providers import registry
from . import prompts, text
from .common import StageError, load_project, model_for, new_asset_path, save_asset
from .context import full_context
from .llm import call_json
from .schemas import ThumbConcepts

THUMB_W, THUMB_H = 1280, 720


def _summary(project) -> str:
    analysis = (project.analysis or {}).get("ai") or {}
    if analysis.get("summary"):
        return analysis["summary"]
    ws = (project.script or "").split()
    return " ".join(ws[:450]) + ("…" if len(ws) > 450 else "")


@handler("thumbnail.concepts")
def thumbnail_concepts(ctx: JobContext) -> dict:
    with session_scope() as db:
        project = load_project(db, ctx.project_id)
        channel = project.channel
        if not (project.script or "").strip():
            raise StageError("Escreva o roteiro antes de criar thumbnails.")
        tier = project.quality
        params = tiers.tier_params(db, tier)
        count = int(ctx.payload.get("count") or params.get("thumb_concepts") or 3)
        variations = int(ctx.payload.get("variations") or params.get("thumb_variations") or 1)
        model = model_for(db, "text", tier)
        titles = []
        if project.selected_title:
            titles.append(project.selected_title)
        titles += [t.get("title", "") for t in ((project.metadata_suggestions or {}).get("titles") or [])][:5]
        system, user = prompts.thumbnail_concepts(
            full_context(db, project), _summary(project), titles, count, text.language_label(channel.language),
            channel.thumbnail_text_mode, channel.thumbnail_style,
        )
        start_pos = max([c.position for c in project.concepts], default=0)
    ctx.progress(0.2, f"criando {count} conceitos de thumbnail", force=True)
    result, _ = call_json(ctx, model=model, system=system, user=user, schema=ThumbConcepts,
                          schema_name="thumbnail_concepts", temperature=0.9, max_tokens=6000, output_units=count)
    created = []
    with session_scope() as db:
        project = load_project(db, ctx.project_id)
        for i, c in enumerate(result.concepts[:count], start=1):
            concept = ThumbnailConcept(
                project_id=project.id, position=start_pos + i, name=c.name, idea=c.idea, emotion=c.emotion,
                composition=c.composition, overlay_text=c.overlay_text[:120], prompt=c.prompt, rationale=c.rationale,
            )
            db.add(concept)
            db.flush()
            created.append(concept.id)
            for v in range(variations):
                ctx.follow_up(db, "thumbnail.image", target_id=concept.id, dedupe=False,
                              label=f"Thumbnail '{c.name[:40]}' v{v + 1}")
    return {"message": f"{len(created)} conceitos criados; {len(created) * variations} imagens na fila",
            "concepts": created}


@handler("thumbnail.image")
def thumbnail_image(ctx: JobContext) -> dict:
    with session_scope() as db:
        concept = db.get(ThumbnailConcept, ctx.target_id)
        if concept is None:
            raise StageError("Conceito de thumbnail não encontrado.")
        project = concept.project
        channel = project.channel
        model = model_for(db, "thumbnail", project.quality)
        resolution = tiers.tier_params(db, project.quality).get("image_resolution")
        prompt = prompts.thumbnail_image_prompt(concept.prompt, concept.overlay_text, channel.thumbnail_text_mode,
                                                channel.thumbnail_style)
        name = concept.name
    ctx.progress(0.1, f"gerando thumbnail '{name[:40]}'", force=True)
    provider, model_id = registry.split_ref(model)
    result = registry.image(provider).generate(model=model_id, prompt=prompt, aspect_ratio="16:9",
                                               resolution=resolution, session_id=f"dm-project-{ctx.project_id}")
    jpg = media.fit_cover(result.data, THUMB_W, THUMB_H, quality=90)
    with session_scope() as db:
        concept = db.get(ThumbnailConcept, ctx.target_id)
        if concept is None:
            raise StageError("Conceito de thumbnail removido durante a geração.")
        asset = save_asset(
            db, project_id=concept.project_id, concept_id=concept.id, kind=AssetKind.THUMBNAIL.value, data=jpg,
            path=new_asset_path(concept.project_id, "thumbnails", f"concept{concept.id}", "jpg"), mime="image/jpeg",
            usage=result.usage, prompt=prompt, params={**result.meta.get("params", {}), "resolution": resolution},
            job_id=ctx.job_id, width=THUMB_W, height=THUMB_H,
        )
        ctx.record(db, result.usage, meta={"resolution": resolution, "asset_id": asset.id})
        if concept.selected_asset_id is None:
            concept.selected_asset_id = asset.id
    return {"message": f"thumbnail '{name[:40]}' pronta", "asset_id": asset.id}
