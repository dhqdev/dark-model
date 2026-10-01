"""Contexto compartilhado por todas as etapas: canal + Skill + aprendizados aprovados."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Channel, Project, Skill, SkillLearning
from . import text


def current_skill(db: Session, channel_id: int) -> Skill | None:
    return db.scalar(select(Skill).where(Skill.channel_id == channel_id).order_by(Skill.version.desc()).limit(1))


def accepted_learnings(db: Session, channel_id: int) -> list[SkillLearning]:
    return list(db.scalars(
        select(SkillLearning).where(SkillLearning.channel_id == channel_id, SkillLearning.status == "accepted")
        .order_by(SkillLearning.id)
    ))


def channel_block(channel: Channel) -> str:
    wpm = channel.words_per_minute or text.default_wpm(channel.language)
    rows = [
        ("Channel", channel.name),
        ("Production language (narration, titles, descriptions, on-screen text)", text.language_label(channel.language)),
        ("Country / market", channel.country or "—"),
        ("Target audience", channel.audience or "—"),
        ("Niche", channel.niche or "—"),
        ("Narrative style", channel.style or "—"),
        ("Tone", channel.tone or "—"),
        ("Target video length", f"{channel.duration_min}–{channel.duration_max} minutes (narration ≈ {wpm} words/min)"),
        ("Visual style", channel.visual_style or "—"),
        ("Thumbnail style", channel.thumbnail_style or "—"),
    ]
    if channel.notes:
        rows.append(("Owner notes", channel.notes))
    return "\n".join(f"- {k}: {v}" for k, v in rows)


def skill_block(db: Session, channel: Channel) -> str:
    skill = current_skill(db, channel.id)
    parts = []
    if skill and skill.content.strip():
        parts.append(f"CHANNEL SKILL v{skill.version} (playbook approved by the channel owner — follow it):\n"
                     f"{skill.content.strip()}")
    learned = accepted_learnings(db, channel.id)
    if learned:
        parts.append("APPROVED LEARNINGS FROM PREVIOUS PROJECTS (also mandatory):\n" +
                     "\n".join(f"- [{item.category}] {item.text}" for item in learned))
    return "\n\n".join(parts) if parts else "CHANNEL SKILL: (empty — use best practices for the niche)"


def project_block(project: Project) -> str:
    rows = [f"- Working title: {project.title}", f"- Quality tier: {project.quality}"]
    if project.notes:
        rows.append(f"- Project notes: {project.notes}")
    return "\n".join(rows)


def full_context(db: Session, project: Project) -> str:
    channel = project.channel
    return (f"## CHANNEL\n{channel_block(channel)}\n\n## {skill_block(db, channel)}\n\n"
            f"## PROJECT\n{project_block(project)}")
