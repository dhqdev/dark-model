"""Peças comuns às etapas: modelos por nível, impressões digitais e gravação de assets."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from .. import catalog, tiers
from ..models import Asset, Channel, Project, Scene, utcnow
from ..providers.base import Usage
from ..storage import get_storage, project_dir
from . import text


class StageError(Exception):
    """Erro de etapa explicável ao usuário (não adianta repetir automaticamente)."""


def model_for(db: Session, op: str, tier: str) -> str:
    resolved = tiers.resolve_model(db, op, tier)
    if not resolved.model:
        raise StageError(
            f"Nenhum modelo disponível para '{tiers.OPERATION_LABELS[op]}' no nível {tier}. "
            "Verifique a chave da OpenRouter e escolha um modelo em Configurações."
        )
    return resolved.model


def effective_scene_seconds(channel: Channel, tier_params: dict[str, Any]) -> float:
    """Segundos por cena: o do canal, respeitando o mínimo do nível (cenas longas = menos imagens)."""
    return max(float(channel.scene_seconds or 7.0), float(tier_params.get("min_scene_seconds") or 0))


def visual_hash(scene: Scene, visual_style: str) -> str:
    return text.content_hash(scene.prompt.strip(), visual_style.strip())


def clip_hash(scene: Scene, visual_style: str) -> str:
    return text.content_hash(scene.prompt.strip(), visual_style.strip(), scene.asset_type, scene.motion)


def tts_settings(db: Session, channel: Channel, tier: str, model: str | None = None) -> dict[str, Any]:
    """Voz da narração: a fixada no canal, senão a do plano do projeto, senão a do nível."""
    model = channel.tts_model or model or model_for(db, "tts", tier)
    voices = catalog.speech_voices(model)
    voice = channel.tts_voice
    warning = ""
    if voices and voice not in voices:
        if voice:
            warning = f"voz '{voice}' não existe em {model}; usada '{voices[0]}'"
        voice = voices[0]
    return {"model": model, "voice": voice, "speed": channel.tts_speed or 1.0,
            "style": channel.tts_style or "", "warning": warning}


def audio_hash(scene: Scene, settings: dict[str, Any]) -> str:
    return text.content_hash(scene.narration.strip(), settings["model"], settings["voice"],
                             round(float(settings["speed"]), 2), settings["style"])


def new_asset_path(project_id: int, folder: str, stem: str, ext: str) -> str:
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    return f"{project_dir(project_id)}/{folder}/{stem}-{stamp}-{uuid.uuid4().hex[:6]}.{ext}"


def save_asset(
    db: Session,
    *,
    project_id: int,
    kind: str,
    data: bytes,
    path: str,
    mime: str,
    scene_id: int | None = None,
    concept_id: int | None = None,
    usage: Usage | None = None,
    prompt: str = "",
    params: dict[str, Any] | None = None,
    source_hash: str = "",
    job_id: int | None = None,
    width: int | None = None,
    height: int | None = None,
    duration: float | None = None,
) -> Asset:
    storage = get_storage()
    size = storage.write_bytes(path, data)
    asset = Asset(
        project_id=project_id, scene_id=scene_id, concept_id=concept_id, kind=kind, path=path, mime=mime,
        size_bytes=size, width=width, height=height, duration=duration,
        provider=usage.provider if usage else "", model=usage.model if usage else "",
        prompt=prompt, params=params or {}, cost_usd=usage.cost_usd if usage else None,
        generation_id=usage.generation_id if usage else None, source_hash=source_hash, job_id=job_id,
    )
    db.add(asset)
    db.flush()
    return asset


def delete_asset_files(db: Session, assets: list[Asset]) -> None:
    storage = get_storage()
    for a in assets:
        storage.delete(a.path)
        db.delete(a)


def scene_timeline(scenes: list[Scene], gap: float = 0.0) -> list[tuple[Scene, float, float]]:
    """(cena, início, duração) usando a duração real do áudio quando existe."""
    out = []
    t = 0.0
    for s in scenes:
        d = s.duration
        out.append((s, t, d))
        t += d + gap
    return out


def load_project(db: Session, project_id: int | None) -> Project:
    project = db.get(Project, project_id) if project_id else None
    if project is None:
        raise StageError("Projeto não encontrado (pode ter sido removido).")
    return project


def load_scene(db: Session, scene_id: int | None) -> Scene:
    scene = db.get(Scene, scene_id) if scene_id else None
    if scene is None:
        raise StageError("Cena não encontrada (pode ter sido removida ou o roteiro foi re-dividido).")
    return scene
