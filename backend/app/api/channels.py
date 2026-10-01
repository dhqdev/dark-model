from __future__ import annotations

import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import catalog, serialize, usage as usage_ledger
from ..deps import get_db, get_or_404, require_user
from ..jobs import queue
from ..models import Channel, Quality, Skill, SkillLearning, utcnow
from ..pipeline import text
from ..pipeline.common import StageError, tts_settings
from ..pipeline.context import current_skill
from ..pipeline.learning import add_skill_version
from ..providers import registry
from ..providers.base import ProviderError
from ..storage import get_storage

router = APIRouter(prefix="/channels", tags=["channels"], dependencies=[Depends(require_user)])


class ChannelIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    language: str = "en-US"
    country: str = ""
    audience: str = ""
    niche: str = ""
    style: str = ""
    tone: str = ""
    duration_min: int = Field(15, ge=1, le=180)
    duration_max: int = Field(25, ge=1, le=240)
    words_per_minute: int | None = Field(None, ge=60, le=400)
    scene_seconds: float = Field(7.0, ge=2, le=30)
    visual_style: str = ""
    default_quality: Quality = Quality.BALANCED
    tts_model: str | None = None
    tts_voice: str | None = None
    tts_speed: float = Field(1.0, ge=0.5, le=2.0)
    tts_style: str = ""
    thumbnail_style: str = ""
    thumbnail_text_mode: str = Field("in_image", pattern="^(in_image|none)$")
    auto_learn: bool = True
    notes: str = ""
    skill: str | None = None


class ChannelPatch(BaseModel):
    name: str | None = None
    language: str | None = None
    country: str | None = None
    audience: str | None = None
    niche: str | None = None
    style: str | None = None
    tone: str | None = None
    duration_min: int | None = Field(None, ge=1, le=180)
    duration_max: int | None = Field(None, ge=1, le=240)
    words_per_minute: int | None = Field(None, ge=0, le=400)
    scene_seconds: float | None = Field(None, ge=2, le=30)
    visual_style: str | None = None
    default_quality: Quality | None = None
    tts_model: str | None = None
    tts_voice: str | None = None
    tts_speed: float | None = Field(None, ge=0.5, le=2.0)
    tts_style: str | None = None
    thumbnail_style: str | None = None
    thumbnail_text_mode: str | None = Field(None, pattern="^(in_image|none)$")
    auto_learn: bool | None = None
    notes: str | None = None
    archived: bool | None = None


class SkillIn(BaseModel):
    content: str
    note: str = ""


class LearningIn(BaseModel):
    text: str = Field(min_length=3)
    category: str = "general"
    rationale: str = ""


class LearningPatch(BaseModel):
    status: str | None = Field(None, pattern="^(proposed|accepted|rejected)$")
    text: str | None = None
    category: str | None = None


class VoicePreviewIn(BaseModel):
    model: str | None = None
    voice: str | None = None
    text: str | None = None
    speed: float | None = Field(None, ge=0.5, le=2.0)


SAMPLE_TEXT = {
    "en": "In the silence of the night, an old secret was waiting to be discovered.",
    "pt": "No silêncio da noite, um antigo segredo esperava para ser descoberto.",
    "es": "En el silencio de la noche, un antiguo secreto esperaba ser descubierto.",
    "de": "In der Stille der Nacht wartete ein altes Geheimnis darauf, entdeckt zu werden.",
    "pl": "W ciszy nocy stara tajemnica czekała na odkrycie.",
    "fr": "Dans le silence de la nuit, un vieux secret attendait d'être découvert.",
    "it": "Nel silenzio della notte, un antico segreto aspettava di essere scoperto.",
}


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()[:120] or "canal"


def unique_slug(db: Session, name: str, exclude_id: int | None = None) -> str:
    base = slugify(name)
    slug, n = base, 2
    while True:
        existing = db.scalar(select(Channel).where(Channel.slug == slug))
        if existing is None or existing.id == exclude_id:
            return slug
        slug = f"{base}-{n}"
        n += 1


def default_skill(c: Channel) -> str:
    return f"""# Skill — {c.name}

## Identidade e público
- Idioma de produção: {text.language_label(c.language)} — narração, títulos, descrição e textos na tela neste idioma.
- Público: {c.audience or 'definir'}
- Nicho: {c.niche or 'definir'}
- Tom: {c.tone or 'definir'} · Estilo narrativo: {c.style or 'definir'}

## Roteiro
- Gancho forte nos primeiros 30 segundos: uma pergunta, um mistério ou uma promessa clara (e cumprida).
- Estrutura em atos com "loops abertos" para manter a retenção; evitar repetir ideias.
- Duração alvo: {c.duration_min}–{c.duration_max} minutos. Fechamento com conclusão + chamada sutil para se inscrever.

## Narração
- Ritmo calmo e envolvente, frases curtas, pausas naturais entre blocos.

## Direção visual
- Estilo: {c.visual_style or 'cinematográfico, iluminação dramática, paleta sóbria'}.
- Variar enquadramentos (geral, médio, detalhe, aéreo). Sem texto, logos ou marcas d'água nas imagens.
- Preferir IMAGEM + MOVIMENTO; usar VÍDEO só em momentos de alto impacto.

## Thumbnails
- Um elemento focal, alto contraste, no máximo 4 palavras. {c.thumbnail_style}

## Títulos e descrição
- Curiosidade sem prometer o que o vídeo não entrega; palavra-chave no início.

## Originalidade e políticas
- Conteúdo original, com pesquisa e valor próprio. Nada de copiar roteiros, letras ou trechos longos.
- Não retratar pessoas reais de forma realista em situações que não aconteceram.
"""


def _get_channel(db: Session, channel_id: int) -> Channel:
    return get_or_404(db, Channel, channel_id, "Canal")


@router.get("")
def list_channels(include_archived: bool = False, db: Session = Depends(get_db)) -> list[dict]:
    q = select(Channel).order_by(Channel.name)
    if not include_archived:
        q = q.where(Channel.archived.is_(False))
    stats = serialize.channel_stats(db)
    return [serialize.channel(c, stats.get(c.id, {})) for c in db.scalars(q)]


@router.post("", status_code=201)
def create_channel(body: ChannelIn, db: Session = Depends(get_db)) -> dict:
    if body.duration_max < body.duration_min:
        raise HTTPException(422, "A duração máxima deve ser maior que a mínima.")
    data = body.model_dump(exclude={"skill"})
    data["default_quality"] = body.default_quality.value
    c = Channel(**data, slug=unique_slug(db, body.name))
    db.add(c)
    db.flush()
    db.add(Skill(channel_id=c.id, version=1, content=body.skill.strip() if body.skill else default_skill(c),
                 note="Skill inicial", source="initial" if not body.skill else "manual"))
    db.commit()
    return serialize.channel(c, {"projects": 0, "cost": 0.0, "skill_version": 1})


@router.get("/{channel_id}")
def get_channel(channel_id: int, db: Session = Depends(get_db)) -> dict:
    c = _get_channel(db, channel_id)
    stats = serialize.channel_stats(db).get(c.id, {})
    return serialize.channel(c, stats)


@router.patch("/{channel_id}")
def update_channel(channel_id: int, body: ChannelPatch, db: Session = Depends(get_db)) -> dict:
    c = _get_channel(db, channel_id)
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] and data["name"] != c.name:
        c.slug = unique_slug(db, data["name"], exclude_id=c.id)
    if "default_quality" in data and data["default_quality"] is not None:
        data["default_quality"] = data["default_quality"].value
    if "words_per_minute" in data and not data["words_per_minute"]:
        data["words_per_minute"] = None
    for key in ("tts_model", "tts_voice"):
        if key in data and not data[key]:
            data[key] = None
    for k, v in data.items():
        if v is not None or k in ("words_per_minute", "tts_model", "tts_voice"):
            setattr(c, k, v)
    if c.duration_max < c.duration_min:
        raise HTTPException(422, "A duração máxima deve ser maior que a mínima.")
    db.commit()
    return serialize.channel(c, serialize.channel_stats(db).get(c.id, {}))


@router.delete("/{channel_id}")
def delete_channel(channel_id: int, confirm: str = "", db: Session = Depends(get_db)) -> dict:
    c = _get_channel(db, channel_id)
    if confirm != c.slug:
        raise HTTPException(400, f"Para excluir definitivamente, confirme com o identificador '{c.slug}'.")
    storage = get_storage()
    for p in c.projects:
        storage.delete_tree(f"projects/{p.id}")
    db.delete(c)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ Skill


@router.get("/{channel_id}/skill")
def get_skill(channel_id: int, db: Session = Depends(get_db)) -> dict:
    _get_channel(db, channel_id)
    versions = list(db.scalars(select(Skill).where(Skill.channel_id == channel_id).order_by(Skill.version.desc())))
    return {
        "current": serialize.skill(versions[0] if versions else None),
        "versions": [{"version": s.version, "note": s.note, "source": s.source, "created_at": serialize.iso(s.created_at),
                      "chars": len(s.content)} for s in versions],
    }


@router.get("/{channel_id}/skill/{version}")
def get_skill_version(channel_id: int, version: int, db: Session = Depends(get_db)) -> dict:
    s = db.scalar(select(Skill).where(Skill.channel_id == channel_id, Skill.version == version))
    if s is None:
        raise HTTPException(404, "Versão não encontrada")
    return serialize.skill(s)


@router.put("/{channel_id}/skill")
def save_skill(channel_id: int, body: SkillIn, db: Session = Depends(get_db)) -> dict:
    _get_channel(db, channel_id)
    cur = current_skill(db, channel_id)
    if cur and cur.content.strip() == body.content.strip():
        return serialize.skill(cur)
    s = add_skill_version(db, channel_id, body.content, note=body.note or "Edição manual", source="manual")
    db.commit()
    return serialize.skill(s)


@router.post("/{channel_id}/skill/restore/{version}")
def restore_skill(channel_id: int, version: int, db: Session = Depends(get_db)) -> dict:
    old = db.scalar(select(Skill).where(Skill.channel_id == channel_id, Skill.version == version))
    if old is None:
        raise HTTPException(404, "Versão não encontrada")
    s = add_skill_version(db, channel_id, old.content, note=f"Restaurada da v{version}", source="restore")
    db.commit()
    return serialize.skill(s)


@router.post("/{channel_id}/skill/draft")
def draft_skill(channel_id: int, db: Session = Depends(get_db)) -> dict:
    c = _get_channel(db, channel_id)
    job = queue.enqueue(db, "skill.draft", label=f"Skill por IA: {c.name}", channel_id=c.id)
    db.commit()
    return serialize.job(job)


@router.post("/{channel_id}/skill/consolidate")
def consolidate_skill(channel_id: int, db: Session = Depends(get_db)) -> dict:
    c = _get_channel(db, channel_id)
    accepted = db.scalar(select(SkillLearning).where(SkillLearning.channel_id == c.id, SkillLearning.status == "accepted"))
    if accepted is None:
        raise HTTPException(400, "Aprove pelo menos um aprendizado antes de consolidar.")
    job = queue.enqueue(db, "skill.consolidate", label=f"Consolidar Skill: {c.name}", channel_id=c.id)
    db.commit()
    return serialize.job(job)


# ------------------------------------------------------------------ aprendizados


@router.get("/{channel_id}/learnings")
def list_learnings(channel_id: int, db: Session = Depends(get_db)) -> list[dict]:
    _get_channel(db, channel_id)
    rows = db.scalars(select(SkillLearning).where(SkillLearning.channel_id == channel_id).order_by(SkillLearning.id.desc()))
    return [serialize.learning(x) for x in rows]


@router.post("/{channel_id}/learnings", status_code=201)
def add_learning(channel_id: int, body: LearningIn, db: Session = Depends(get_db)) -> dict:
    _get_channel(db, channel_id)
    item = SkillLearning(channel_id=channel_id, category=body.category, text=body.text.strip(),
                         rationale=body.rationale, status="accepted", source="manual", decided_at=utcnow())
    db.add(item)
    db.commit()
    return serialize.learning(item)


@router.patch("/learnings/{learning_id}")
def update_learning(learning_id: int, body: LearningPatch, db: Session = Depends(get_db)) -> dict:
    item = get_or_404(db, SkillLearning, learning_id, "Aprendizado")
    if body.text is not None:
        item.text = body.text.strip()
    if body.category is not None:
        item.category = body.category
    if body.status is not None and body.status != item.status:
        item.status = body.status
        item.decided_at = utcnow()
    db.commit()
    return serialize.learning(item)


@router.delete("/learnings/{learning_id}")
def delete_learning(learning_id: int, db: Session = Depends(get_db)) -> dict:
    item = get_or_404(db, SkillLearning, learning_id, "Aprendizado")
    db.delete(item)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ voz


@router.get("/{channel_id}/voices")
def channel_voices(channel_id: int, model: str | None = None, db: Session = Depends(get_db)) -> dict:
    c = _get_channel(db, channel_id)
    try:
        settings = tts_settings(db, c, c.default_quality)
    except StageError as exc:
        settings = {"model": None, "voice": None, "warning": str(exc)}
    target = model or settings["model"]
    return {"model": target, "voices": catalog.speech_voices(target) if target else [],
            "effective": settings}


@router.post("/{channel_id}/voice-preview")
def voice_preview(channel_id: int, body: VoicePreviewIn, db: Session = Depends(get_db)) -> Response:
    c = _get_channel(db, channel_id)
    try:
        usage_ledger.check_budget(db, None)
        settings = tts_settings(db, c, c.default_quality)
    except (usage_ledger.BudgetExceeded, StageError) as exc:
        raise HTTPException(400, str(exc)) from exc
    model = body.model or settings["model"]
    voice = body.voice or settings["voice"]
    sample = (body.text or SAMPLE_TEXT.get(text.lang_base(c.language), SAMPLE_TEXT["en"]))[:400]
    provider, model_id = registry.split_ref(model)
    try:
        res = registry.tts(provider).synthesize(model=model_id, text=sample, voice=voice,
                                                speed=body.speed or c.tts_speed, style=c.tts_style or None)
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    usage_ledger.record(db, res.usage, stage="narration", channel_id=c.id, meta={"preview": True, "voice": voice})
    db.commit()
    headers = {"X-Cost-USD": "" if res.usage.cost_usd is None else f"{res.usage.cost_usd:.6f}",
               "X-Voice": voice or "", "X-Model": model_id}
    return Response(content=res.data, media_type="audio/mpeg", headers=headers)
