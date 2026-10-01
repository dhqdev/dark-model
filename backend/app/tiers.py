"""Níveis de qualidade (ECONOMY / BALANCED / PREMIUM) e escolha de modelos por etapa.

Cada nível define um modelo por operação. O usuário pode fixar qualquer modelo nas
Configurações; quando não fixado, o modelo é escolhido no catálogo real da OpenRouter:
primeiro pelas famílias preferidas (a versão mais nova disponível) e, se nenhuma existir,
pela faixa de preço (mais barato / mediano / mais caro).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from statistics import median
from typing import Any

from sqlalchemy.orm import Session

from . import catalog
from .models import AppSetting, Quality, utcnow

OPERATIONS = ("text", "image", "thumbnail", "tts", "video")
OPERATION_LABELS = {
    "text": "Texto (análise, cenas, metadados)",
    "image": "Imagens das cenas",
    "thumbnail": "Thumbnails",
    "tts": "Narração (TTS)",
    "video": "Vídeo IA",
}
CATALOG_KIND = {"text": "text", "image": "image", "thumbnail": "image", "tts": "speech", "video": "video"}

TIER_PARAMS: dict[str, dict[str, Any]] = {
    # min_scene_seconds: cenas mais longas = menos imagens (a imagem é o maior custo do vídeo)
    # cap_brl: teto por vídeo em reais (0 = sem teto); o plano é ajustado para caber
    Quality.ECONOMY: {
        "image_resolution": "1K", "video_resolution": "480p", "thumb_concepts": 2, "thumb_variations": 1,
        "video_share": 0.0, "reasoning": "low", "min_scene_seconds": 12, "cap_brl": 0,
    },
    Quality.BALANCED: {
        "image_resolution": "1K", "video_resolution": "720p", "thumb_concepts": 3, "thumb_variations": 2,
        "video_share": 0.03, "reasoning": None, "min_scene_seconds": 9, "cap_brl": 20,
    },
    Quality.PREMIUM: {
        "image_resolution": "2K", "video_resolution": "1080p", "thumb_concepts": 4, "thumb_variations": 2,
        "video_share": 0.10, "reasoning": "medium", "min_scene_seconds": 0, "cap_brl": 50,
    },
}

_V = r"[\d]+(?:\.[\d]+)?"
PREFERRED: dict[str, dict[str, list[str]]] = {
    "text": {
        Quality.ECONOMY: [rf"^google/gemini-{_V}-flash(-preview)?$", rf"^anthropic/claude-haiku-{_V}$",
                          rf"^openai/gpt-{_V}-mini$", r"^deepseek/deepseek-(chat|v)[\w.-]*$"],
        Quality.BALANCED: [rf"^anthropic/claude-sonnet-{_V}$", rf"^google/gemini-{_V}-pro(-preview)?$",
                           rf"^openai/gpt-{_V}$"],
        Quality.PREMIUM: [rf"^anthropic/claude-opus-{_V}$", rf"^openai/gpt-{_V}$",
                          rf"^google/gemini-{_V}-pro(-preview)?$"],
    },
    "image": {
        # o mais barato entre famílias realistas e fiéis ao prompt (se nenhuma existir: o mais barato do catálogo)
        Quality.ECONOMY: [rf"^(google/gemini-{_V}-flash-image(-preview)?|bytedance-seed/seedream[\w.-]*|"
                          rf"black-forest-labs/flux[\w.-]*|qwen/qwen[\w.-]*image[\w.-]*|openai/gpt-image-{_V}-mini)$"],
        Quality.BALANCED: [rf"^google/gemini-{_V}-flash-image(-preview)?$", rf"^openai/gpt-image-{_V}-mini$"],
        Quality.PREMIUM: [rf"^google/gemini-{_V}-pro-image(-preview)?$", rf"^openai/gpt-image-{_V}$",
                          rf"^openai/gpt-{_V}-image$"],
    },
    "thumbnail": {
        Quality.ECONOMY: [rf"^google/gemini-{_V}-flash-image(-preview)?$"],
        Quality.BALANCED: [rf"^google/gemini-{_V}-flash-image(-preview)?$", rf"^openai/gpt-image-{_V}-mini$"],
        Quality.PREMIUM: [rf"^google/gemini-{_V}-pro-image(-preview)?$", rf"^openai/gpt-image-{_V}$",
                          rf"^openai/gpt-{_V}-image$"],
    },
    "tts": {
        Quality.ECONOMY: [r"^google/gemini-[\w.-]*flash[\w.-]*tts", r"^mistralai/voxtral[\w.-]*tts", r"^x-ai/grok[\w.-]*tts"],
        Quality.BALANCED: [r"^openai/[\w.-]*tts", r"^google/gemini-[\w.-]*flash[\w.-]*tts"],
        Quality.PREMIUM: [r"^elevenlabs/", r"^google/gemini-[\w.-]*pro[\w.-]*tts", r"^openai/[\w.-]*tts"],
    },
    "video": {
        Quality.ECONOMY: [r"^alibaba/wan[\w.-]*", r"^bytedance/seedance[\w.-]*lite"],
        Quality.BALANCED: [r"^bytedance/seedance[\w.-]*", r"^kwaivgi/kling[\w.-]*", r"^minimax/hailuo[\w.-]*"],
        Quality.PREMIUM: [r"^google/veo[\w.-]*", r"^openai/sora[\w.-]*pro", r"^openai/sora[\w.-]*"],
    },
}


# nessas operações o preço por unidade domina o custo do vídeo: fora do Premium, dentro da família
# preferida vale a versão mais barata com preço real (não a mais nova)
PRICE_FIRST = ("image", "thumbnail", "video")


@dataclass
class Resolved:
    model: str | None
    source: str  # config | preferred | auto | missing
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_tier_settings(db: Session) -> dict[str, dict[str, Any]]:
    row = db.get(AppSetting, "tiers")
    stored = dict(row.value) if row and isinstance(row.value, dict) else {}
    out: dict[str, dict[str, Any]] = {}
    for tier in Quality:
        cfg = dict(TIER_PARAMS[tier])
        cfg.update({op: None for op in OPERATIONS})
        cfg.update({k: v for k, v in (stored.get(tier.value) or {}).items() if k in cfg})
        out[tier.value] = cfg
    return out


def save_tier_settings(db: Session, data: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    current = get_tier_settings(db)
    for tier, cfg in data.items():
        if tier not in current:
            continue
        for k, v in cfg.items():
            if k in current[tier]:
                current[tier][k] = v if v not in ("", None) else (None if k in OPERATIONS else TIER_PARAMS[Quality(tier)][k])
    row = db.get(AppSetting, "tiers")
    if row is None:
        db.add(AppSetting(key="tiers", value=current))
    else:
        row.value = current
        row.updated_at = utcnow()
    return current


_NOT_TEXT_TO_IMAGE = re.compile(
    r"(edit|kontext|upscal|inpaint|outpaint|remov|background|vector|svg|quiver|relight|restor|fill)", re.I
)


def _version_key(model: dict[str, Any]) -> tuple:
    return (model.get("created") or 0, model.get("id") or "")


def _candidates(op: str) -> list[dict[str, Any]]:
    kind = CATALOG_KIND[op]
    if kind == "image":
        items = catalog.safe_get(catalog.KINDS["image"])
        ids = {m.get("id") for m in items}
        items = items + [m for m in catalog.safe_get(catalog.KINDS["image_chat"]) if m.get("id") not in ids]
    else:
        items = catalog.safe_get(catalog.KINDS[kind])
    out = []
    for m in items:
        mid = str(m.get("id") or "")
        if not mid or ":" in mid:
            continue  # variantes como ":free" têm limites de uso
        if op == "text":
            params = set(m.get("supported_parameters") or [])
            if params and not ({"response_format", "structured_outputs"} & params):
                continue
            outs = (m.get("architecture") or {}).get("output_modalities") or ["text"]
            if "text" not in outs:
                continue
        if op == "video" and (m.get("upscale_factor") or m.get("creativity")):
            continue  # modelos de upscale não geram vídeo
        if CATALOG_KIND[op] == "image" and _NOT_TEXT_TO_IMAGE.search(mid):
            continue  # edição, upscale, remoção de fundo, vetorização
        out.append(m)
    return out


def _price_key(db: Session, op: str, m: dict[str, Any], tier: str) -> float | None:
    """Custo comparável entre modelos da mesma operação (só com preço real)."""
    from . import pricing

    if op == "text":
        p = pricing.token_prices(m)
        return None if p is None else p[0] * 3 + p[1]
    if op == "tts":
        p = pricing.token_prices(m)
        if p is None:
            return None
        # custo de ~1.000 caracteres (~67 s de áudio); cobrança por caractere ou por token
        if p[1]:
            return 250 * p[0] + 67 * pricing.AUDIO_TOKENS_PER_SECOND * p[1]
        return 1000 * p[0]
    if op in ("image", "thumbnail"):
        c = pricing.image_cost(db, m["id"], TIER_PARAMS[Quality(tier)]["image_resolution"])
        return c.value if c.source in ("live", "history") else None
    if op == "video":
        cost, _ = pricing.video_skus_cost(m.get("pricing_skus") or {}, resolution="720p", duration=5)
        return cost
    return None


def _priced(db: Session, op: str, tier: str, cands: list[dict[str, Any]]) -> list[tuple[float, dict[str, Any]]]:
    if CATALOG_KIND[op] == "image":
        catalog.prefetch_image_endpoints([m["id"] for m in cands])
    return [(k, m) for m in cands if (k := _price_key(db, op, m, tier)) is not None and k > 0]


def _cheapest(db: Session, op: str, tier: str, cands: list[dict[str, Any]]) -> dict[str, Any] | None:
    priced = _priced(db, op, tier, cands)
    if not priced:
        return None
    # empate de preço: a versão mais nova
    return min(priced, key=lambda x: (x[0], -(x[1].get("created") or 0)))[1]


def _auto_pick(db: Session, op: str, tier: str, cands: list[dict[str, Any]]) -> dict[str, Any] | None:
    priced = _priced(db, op, tier, cands)
    if priced:
        priced.sort(key=lambda x: x[0])
        if tier == Quality.ECONOMY:
            return priced[0][1]
        if tier == Quality.PREMIUM:
            return priced[-1][1]
        mid = median(k for k, _ in priced)
        return min(priced, key=lambda x: abs(x[0] - mid))[1]
    if cands:
        return max(cands, key=_version_key)
    return None


def resolve_model(db: Session, op: str, tier: str, *, settings: dict[str, Any] | None = None) -> Resolved:
    cfg = (settings or get_tier_settings(db))[tier]
    configured = cfg.get(op)
    if configured:
        return Resolved(configured, "config")
    cands = _candidates(op)
    for pattern in PREFERRED[op][Quality(tier)]:
        rx = re.compile(pattern)
        matches = [m for m in cands if rx.search(str(m.get("id")))]
        if matches:
            if op in PRICE_FIRST and tier != Quality.PREMIUM:
                cheapest = _cheapest(db, op, tier, matches)
                if cheapest:
                    return Resolved(cheapest["id"], "preferred", "família preferida, opção mais barata (preço real)")
            best = max(matches, key=_version_key)
            return Resolved(best["id"], "preferred", "família preferida, versão mais nova do catálogo")
    picked = _auto_pick(db, op, tier, cands)
    if picked:
        note = ("o mais barato do catálogo (preço real)" if tier == Quality.ECONOMY
                else "escolhido pela faixa de preço do catálogo")
        return Resolved(picked["id"], "auto", note)
    return Resolved(None, "missing", "nenhum modelo compatível no catálogo da OpenRouter")


def resolve_all(db: Session) -> dict[str, dict[str, Any]]:
    settings = get_tier_settings(db)
    out: dict[str, dict[str, Any]] = {}
    for tier in Quality:
        out[tier.value] = {op: resolve_model(db, op, tier.value, settings=settings).to_dict() for op in OPERATIONS}
    return out


def tier_params(db: Session, tier: str) -> dict[str, Any]:
    return get_tier_settings(db)[tier]
