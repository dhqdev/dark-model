"""Skill do canal: rascunho por IA, extração de aprendizados e consolidação em nova versão."""

from __future__ import annotations

from sqlalchemy import select

from ..db import session_scope
from ..jobs.context import JobContext, handler
from ..models import Channel, FeedbackEvent, Quality, Skill, SkillLearning, utcnow
from . import prompts, text
from .common import StageError, model_for
from .context import accepted_learnings, channel_block, current_skill
from .llm import call_json
from .schemas import Learnings, SkillDocument


def add_skill_version(db, channel_id: int, content: str, *, note: str, source: str) -> Skill:
    last = current_skill(db, channel_id)
    skill = Skill(channel_id=channel_id, version=(last.version + 1) if last else 1, content=content,
                  note=note[:400], source=source)
    db.add(skill)
    db.flush()
    return skill


@handler("skill.draft")
def draft_skill(ctx: JobContext) -> dict:
    with session_scope() as db:
        channel = db.get(Channel, ctx.channel_id)
        if channel is None:
            raise StageError("Canal não encontrado.")
        model = model_for(db, "text", channel.default_quality or Quality.BALANCED.value)
        system, user = prompts.skill_draft(channel_block(channel), text.language_label(channel.language))
    ctx.progress(0.2, "escrevendo a Skill do canal", force=True)
    result, _ = call_json(ctx, model=model, system=system, user=user, schema=SkillDocument,
                          schema_name="skill_document", temperature=0.6, max_tokens=8000)
    with session_scope() as db:
        skill = add_skill_version(db, ctx.channel_id, result.content.strip(),
                                  note=f"Rascunho gerado por IA — {result.summary}", source="ai_draft")
    return {"message": f"Skill v{skill.version} criada pela IA", "version": skill.version}


def _feedback_text(events: list[FeedbackEvent]) -> str:
    lines = []
    for e in events[-80:]:
        d = e.data or {}
        if e.kind == "scene_prompt_edited":
            lines.append(f"- Edited a scene prompt. Before: {d.get('before', '')[:200]} | After: {d.get('after', '')[:200]}")
        elif e.kind == "scene_asset_type_changed":
            lines.append(f"- Changed asset type from {d.get('before')} to {d.get('after')} (scene: {d.get('narration', '')[:100]})")
        elif e.kind == "scene_rewrite_instruction":
            lines.append(f"- Asked to redesign a scene: \"{d.get('instruction', '')[:200]}\"")
        elif e.kind == "title_selected":
            lines.append(f"- Chose the title: \"{d.get('title', '')}\" (other options: {', '.join(d.get('options', [])[:4])})")
        elif e.kind == "thumbnail_selected":
            lines.append(f"- Chose thumbnail concept \"{d.get('name', '')}\": {d.get('idea', '')[:160]} | text: {d.get('overlay_text', '')}")
        elif e.kind == "narration_edited":
            lines.append(f"- Edited narration. Before: {d.get('before', '')[:160]} | After: {d.get('after', '')[:160]}")
        elif e.kind == "description_edited":
            lines.append(f"- Rewrote the description (final starts with): {d.get('after', '')[:200]}")
        else:
            lines.append(f"- {e.kind}: {str(d)[:200]}")
    return "\n".join(lines)


@handler("skill.learn")
def extract_learnings(ctx: JobContext) -> dict:
    with session_scope() as db:
        from ..models import Project

        project = db.get(Project, ctx.project_id)
        if project is None:
            raise StageError("Projeto não encontrado.")
        channel = project.channel
        events = list(db.scalars(select(FeedbackEvent).where(FeedbackEvent.project_id == project.id)
                                 .order_by(FeedbackEvent.id)))
        analysis = (project.analysis or {}).get("ai") or {}
        scenes = list(project.scenes)
        types: dict[str, int] = {}
        for s in scenes:
            types[s.asset_type] = types.get(s.asset_type, 0) + 1
        summary = "\n".join([
            f"- Title chosen: {project.selected_title or '—'}",
            f"- Script verdict: {analysis.get('verdict', '—')}; summary: {analysis.get('summary', '—')[:500]}",
            f"- Main improvements suggested: {'; '.join(analysis.get('improvements', [])[:5])}",
            f"- Scenes: {len(scenes)}; asset types: {types}",
            "- Sample of final scene prompts: " + " || ".join(s.prompt[:160] for s in scenes[:: max(1, len(scenes) // 6)][:6]),
            f"- Final description starts with: {project.description[:300]}",
        ])
        skill = current_skill(db, channel.id)
        accepted = [f"[{a.category}] {a.text}" for a in accepted_learnings(db, channel.id)]
        model = model_for(db, "text", project.quality)
        system, user = prompts.learnings(skill.content if skill else "", accepted, summary, _feedback_text(events))
        event_ids = [e.id for e in events]
    ctx.progress(0.2, "extraindo aprendizados do projeto", force=True)
    result, _ = call_json(ctx, model=model, system=system, user=user, schema=Learnings, schema_name="learnings",
                          temperature=0.4, max_tokens=4000)
    with session_scope() as db:
        for item in result.learnings[:8]:
            db.add(SkillLearning(channel_id=ctx.channel_id, project_id=ctx.project_id, category=item.category,
                                 text=item.text.strip(), rationale=item.rationale.strip(), status="proposed", source="ai"))
        for ev in db.scalars(select(FeedbackEvent).where(FeedbackEvent.id.in_(event_ids))):
            ev.consumed = True
    return {"message": f"{len(result.learnings[:8])} aprendizados propostos para revisão"}


@handler("skill.consolidate")
def consolidate_skill(ctx: JobContext) -> dict:
    with session_scope() as db:
        channel = db.get(Channel, ctx.channel_id)
        if channel is None:
            raise StageError("Canal não encontrado.")
        learned = accepted_learnings(db, channel.id)
        if not learned:
            raise StageError("Não há aprendizados aprovados para consolidar.")
        skill = current_skill(db, channel.id)
        model = model_for(db, "text", channel.default_quality or Quality.BALANCED.value)
        system, user = prompts.skill_consolidate(skill.content if skill else "",
                                                 [f"[{a.category}] {a.text}" for a in learned])
        ids = [a.id for a in learned]
    ctx.progress(0.2, f"integrando {len(ids)} aprendizados na Skill", force=True)
    result, _ = call_json(ctx, model=model, system=system, user=user, schema=SkillDocument,
                          schema_name="skill_document", temperature=0.3, max_tokens=10000)
    with session_scope() as db:
        new = add_skill_version(db, ctx.channel_id, result.content.strip(),
                                note=f"Consolidação de {len(ids)} aprendizados — {result.summary}", source="consolidation")
        for item in db.scalars(select(SkillLearning).where(SkillLearning.id.in_(ids))):
            item.status = "merged"
            item.decided_at = utcnow()
    return {"message": f"Skill v{new.version} criada com {len(ids)} aprendizados", "version": new.version}
