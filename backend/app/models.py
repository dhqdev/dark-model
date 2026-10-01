"""Modelo de dados: Canal → Skill/Aprendizados → Projeto → Cenas → Assets, + fila e custos."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    """Horário UTC sem fuso (o banco guarda tudo em UTC)."""
    return datetime.now(UTC).replace(tzinfo=None)


class Quality(StrEnum):
    ECONOMY = "ECONOMY"
    BALANCED = "BALANCED"
    PREMIUM = "PREMIUM"


class AssetType(StrEnum):
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    IMAGE_MOTION = "IMAGE_MOTION"


class Motion(StrEnum):
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"
    PAN_UP = "pan_up"
    PAN_DOWN = "pan_down"
    STATIC = "static"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class Stage(StrEnum):
    SCRIPT = "script"
    SCENES = "scenes"
    VISUALS = "visuals"
    NARRATION = "narration"
    THUMBNAIL = "thumbnail"
    METADATA = "metadata"
    EXPORT = "export"
    LEARNING = "learning"


class AssetKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    MOTION = "motion"
    AUDIO = "audio"
    NARRATION = "narration"
    THUMBNAIL = "thumbnail"
    EXPORT = "export"
    FINAL = "final"  # vídeo final montado (imagens/vídeos + narração + transições + texto + efeitos)


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(180), unique=True)
    language: Mapped[str] = mapped_column(String(16), default="en-US")
    country: Mapped[str] = mapped_column(String(8), default="")
    audience: Mapped[str] = mapped_column(Text, default="")
    niche: Mapped[str] = mapped_column(String(240), default="")
    style: Mapped[str] = mapped_column(Text, default="")
    tone: Mapped[str] = mapped_column(String(240), default="")
    duration_min: Mapped[int] = mapped_column(Integer, default=15)
    duration_max: Mapped[int] = mapped_column(Integer, default=25)
    words_per_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scene_seconds: Mapped[float] = mapped_column(Float, default=7.0)
    visual_style: Mapped[str] = mapped_column(Text, default="")
    default_quality: Mapped[str] = mapped_column(String(16), default=Quality.BALANCED.value)
    tts_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    tts_voice: Mapped[str | None] = mapped_column(String(160), nullable=True)
    tts_speed: Mapped[float] = mapped_column(Float, default=1.0)
    tts_style: Mapped[str] = mapped_column(Text, default="")
    thumbnail_style: Mapped[str] = mapped_column(Text, default="")
    thumbnail_text_mode: Mapped[str] = mapped_column(String(16), default="in_image")
    auto_learn: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    projects: Mapped[list[Project]] = relationship(back_populates="channel", cascade="all, delete-orphan")
    skills: Mapped[list[Skill]] = relationship(
        back_populates="channel", cascade="all, delete-orphan", order_by="Skill.version"
    )
    learnings: Mapped[list[SkillLearning]] = relationship(back_populates="channel", cascade="all, delete-orphan")


class Skill(Base):
    """Versão da Skill do canal. A versão mais alta é a atual; as anteriores ficam no histórico."""

    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("channel_id", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(String(400), default="")
    # initial | manual | ai_draft | consolidation | restore
    source: Mapped[str] = mapped_column(String(32), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    channel: Mapped[Channel] = relationship(back_populates="skills")


class SkillLearning(Base):
    """Aprendizado proposto pela IA (ou pelo usuário) a partir dos projetos do canal."""

    __tablename__ = "skill_learnings"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    # script | scenes | visuals | narration | thumbnail | metadata | general
    category: Mapped[str] = mapped_column(String(32), default="general")
    text: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, default="")
    # proposed | accepted | rejected | merged
    status: Mapped[str] = mapped_column(String(16), default="proposed", index=True)
    source: Mapped[str] = mapped_column(String(16), default="ai")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    channel: Mapped[Channel] = relationship(back_populates="learnings")


class FeedbackEvent(Base):
    """Sinais do usuário (edições, escolhas, regenerações) usados para evoluir a Skill."""

    __tablename__ = "feedback_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    scene_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(48))
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    # draft | script | scenes | production | ready | exported
    status: Mapped[str] = mapped_column(String(24), default="draft")
    quality: Mapped[str] = mapped_column(String(16), default=Quality.BALANCED.value)
    script: Mapped[str] = mapped_column(Text, default="")
    script_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    analysis: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    analysis_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    analysis_script_hash: Mapped[str] = mapped_column(String(64), default="")
    scenes_planned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scenes_script_hash: Mapped[str] = mapped_column(String(64), default="")
    target_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    # plano de produção dentro do teto do nível (modelo de imagem, duração das cenas, % de vídeo)
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    metadata_suggestions: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    selected_title: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    channel: Mapped[Channel] = relationship(back_populates="projects")
    scenes: Mapped[list[Scene]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Scene.position"
    )
    concepts: Mapped[list[ThumbnailConcept]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ThumbnailConcept.position"
    )


class Scene(Base):
    __tablename__ = "scenes"
    __table_args__ = (Index("ix_scenes_project_position", "project_id", "position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    narration: Mapped[str] = mapped_column(Text, default="")
    est_duration: Mapped[float] = mapped_column(Float, default=0.0)
    audio_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    visual_description: Mapped[str] = mapped_column(Text, default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    asset_type: Mapped[str] = mapped_column(String(16), default=AssetType.IMAGE_MOTION.value)
    ai_asset_type: Mapped[str] = mapped_column(String(16), default=AssetType.IMAGE_MOTION.value)
    asset_type_reason: Mapped[str] = mapped_column(Text, default="")
    motion: Mapped[str] = mapped_column(String(16), default=Motion.ZOOM_IN.value)
    sentence_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sentence_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # edição do vídeo final: transição de entrada, efeito sonoro e texto na tela (máquina de escrever)
    transition: Mapped[str] = mapped_column(String(16), default="dissolve", server_default="dissolve")
    sfx: Mapped[str] = mapped_column(String(16), default="none", server_default="none")
    overlay_text: Mapped[str] = mapped_column(String(120), default="", server_default="")
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    # assets escolhidos (sem FK para evitar dependência circular; mantidos pela aplicação)
    image_asset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clip_asset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_asset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    project: Mapped[Project] = relationship(back_populates="scenes")

    @property
    def duration(self) -> float:
        """Duração real (áudio gerado) ou a estimada pela velocidade de narração."""
        return float(self.audio_duration or self.est_duration or 0.0)


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    scene_id: Mapped[int | None] = mapped_column(
        ForeignKey("scenes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    concept_id: Mapped[int | None] = mapped_column(
        ForeignKey("thumbnail_concepts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    path: Mapped[str] = mapped_column(String(600))
    mime: Mapped[str] = mapped_column(String(80), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider: Mapped[str] = mapped_column(String(40), default="")
    model: Mapped[str] = mapped_column(String(160), default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    generation_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # impressão digital das entradas (prompt, tipo, voz...) para detectar asset desatualizado
    source_hash: Mapped[str] = mapped_column(String(64), default="")
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ThumbnailConcept(Base):
    __tablename__ = "thumbnail_concepts"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(200), default="")
    idea: Mapped[str] = mapped_column(Text, default="")
    emotion: Mapped[str] = mapped_column(String(200), default="")
    composition: Mapped[str] = mapped_column(Text, default="")
    overlay_text: Mapped[str] = mapped_column(String(120), default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    selected_asset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="concepts")


class Job(Base):
    """Tarefa assíncrona. Lotes (ex.: 'gerar todas as imagens') são um job pai com filhos."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_claim", "status", "priority", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(48))
    stage: Mapped[str] = mapped_column(String(16), default="")
    lane: Mapped[str] = mapped_column(String(16), default="llm")
    label: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.QUEUED.value, index=True)
    channel_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    scene_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    is_group: Mapped[bool] = mapped_column(Boolean, default=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(String(400), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    worker_id: Mapped[str] = mapped_column(String(80), default="")
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    run_after: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class UsageRecord(Base):
    """Livro-caixa: cada chamada a um provider, com tokens e custo real informado pela API."""

    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    channel_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    scene_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stage: Mapped[str] = mapped_column(String(16), default="")
    operation: Mapped[str] = mapped_column(String(16), default="llm")
    provider: Mapped[str] = mapped_column(String(40), default="openrouter")
    model: Mapped[str] = mapped_column(String(160), default="")
    generation_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    units: Mapped[float] = mapped_column(Float, default=0.0)
    unit: Mapped[str] = mapped_column(String(16), default="")
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    # reported (devolvido na resposta) | generation (consultado em /generation) |
    # pending (aguardando a OpenRouter) | free (processamento local) | unknown
    cost_source: Mapped[str] = mapped_column(String(16), default="reported")
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class CatalogEntry(Base):
    """Cache dos catálogos da OpenRouter (modelos, preços, vozes)."""

    __tablename__ = "catalog_entries"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    data: Mapped[Any] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(120), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    info: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
