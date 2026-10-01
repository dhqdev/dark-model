"""Preços unitários a partir do catálogo real da OpenRouter e do histórico de custos reais.

Toda estimativa informa a origem:
  live       preço publicado no catálogo da OpenRouter
  history    média dos custos reais já cobrados neste sistema para o mesmo modelo
  heuristic  preço real, mas a quantidade (tokens por imagem/áudio) é aproximada
  free       processamento local, sem custo
  unavailable  sem dados suficientes — o custo real aparece após a geração
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import catalog
from .models import UsageRecord

# Imagens geradas por modelos cobrados por token (ex.: Gemini 1024px ≈ 1290 tokens de saída).
TOKENS_PER_IMAGE = {"512": 640, "768": 1000, "1K": 1290, "2K": 1680, "4K": 2520}
# Áudio em modelos TTS cobrados por token (ex.: Gemini ≈ 32 tokens por segundo de áudio).
AUDIO_TOKENS_PER_SECOND = 32
VIDEO_TOKEN_FPS = 24
RES_DIMS = {
    "360p": (640, 360), "480p": (854, 480), "720p": (1280, 720), "768p": (1366, 768),
    "1080p": (1920, 1080), "1K": (1024, 576), "2K": (2048, 1152), "4K": (3840, 2160),
}


@dataclass
class Cost:
    value: float | None
    source: str
    note: str = ""


def _f(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def token_prices(model: dict[str, Any] | None) -> tuple[float, float] | None:
    """(USD por token de entrada, USD por token de saída)."""
    if not model:
        return None
    p = model.get("pricing") or {}
    prompt, completion = _f(p.get("prompt")), _f(p.get("completion"))
    if prompt is None and completion is None:
        return None
    if (prompt or 0) < 0 or (completion or 0) < 0:
        return None  # modelos "router" usam -1 (preço variável)
    return prompt or 0.0, completion or 0.0


def llm_cost(model_id: str, tokens_in: int, tokens_out: int) -> Cost:
    prices = token_prices(catalog.model_info(model_id))
    if prices is None:
        return Cost(None, "unavailable", "modelo sem preço no catálogo")
    return Cost(tokens_in * prices[0] + tokens_out * prices[1], "live")


# ------------------------------------------------------------------ histórico real


def history_unit_cost(db: Session, model: str, operation: str, *, limit: int = 60,
                      meta_key: str | None = None, meta_value: Any = None) -> tuple[float, int] | None:
    """Custo médio real por unidade (imagem, caractere, segundo) dos últimos registros."""
    rows = db.execute(
        select(UsageRecord.cost_usd, UsageRecord.units, UsageRecord.meta)
        .where(UsageRecord.model == model, UsageRecord.operation == operation,
               UsageRecord.cost_usd.is_not(None), UsageRecord.units > 0)
        .order_by(UsageRecord.id.desc()).limit(limit)
    ).all()
    if meta_key is not None:
        rows = [r for r in rows if (r.meta or {}).get(meta_key) == meta_value]
    if not rows:
        return None
    cost = sum(r.cost_usd for r in rows)
    units = sum(r.units for r in rows)
    return (cost / units, len(rows)) if units else None


def history_tokens(db: Session, stage: str, model: str | None = None, limit: int = 30) -> dict[str, float] | None:
    """Média real de tokens por chamada em uma etapa (calibra as estimativas de texto)."""
    q = select(UsageRecord.prompt_tokens, UsageRecord.completion_tokens, UsageRecord.meta).where(
        UsageRecord.stage == stage, UsageRecord.operation == "llm", UsageRecord.total_tokens > 0
    )
    if model:
        q = q.where(UsageRecord.model == model)
    rows = db.execute(q.order_by(UsageRecord.id.desc()).limit(limit)).all()
    if not rows:
        return None
    n = len(rows)
    out = {"prompt": sum(r.prompt_tokens for r in rows) / n, "completion": sum(r.completion_tokens for r in rows) / n,
           "samples": n}
    units = [float((r.meta or {}).get("output_units") or 0) for r in rows]
    if all(units):
        out["completion_per_unit"] = sum(r.completion_tokens for r in rows) / sum(units)
    return out


# ------------------------------------------------------------------ imagem


def _image_pixels(resolution: str | None) -> float:
    w, h = RES_DIMS.get(resolution or "1K", (1024, 576))
    return w * h / 1_000_000


def image_cost(db: Session, model_id: str, resolution: str | None) -> Cost:
    hist = history_unit_cost(db, model_id, "image", meta_key="resolution", meta_value=resolution) or \
        history_unit_cost(db, model_id, "image")
    if hist:
        return Cost(hist[0], "history", f"média real de {hist[1]} imagens")
    if catalog.image_caps(model_id) is not None:
        endpoints = catalog.image_endpoints(model_id)
        if endpoints:
            entries = [e for e in (endpoints[0].get("pricing") or []) if e.get("billable") == "output_image"]
            if resolution:
                exact = [e for e in entries if str(e.get("variant") or "").upper() == resolution.upper()]
                entries = exact or [e for e in entries if not e.get("variant")] or entries
            if entries:
                e = max(entries, key=lambda x: float(x.get("cost_usd") or 0))
                price = float(e.get("cost_usd") or 0)
                unit = e.get("unit")
                if unit in ("image", "request"):
                    return Cost(price, "live", f"preço por imagem ({e.get('variant') or 'padrão'})")
                if unit == "megapixel":
                    return Cost(price * _image_pixels(resolution), "live", "preço por megapixel")
                if unit == "token":
                    tokens = TOKENS_PER_IMAGE.get(resolution or "1K", 1290)
                    return Cost(price * tokens, "heuristic", f"≈{tokens} tokens por imagem")
    info = catalog.model_info(model_id)
    if info:
        p = info.get("pricing") or {}
        per_image = _f(p.get("image_output"))
        if per_image and per_image >= 0.001:
            return Cost(per_image, "live", "preço por imagem")
        per_token = per_image or _f(p.get("completion"))
        if per_token:
            tokens = TOKENS_PER_IMAGE.get(resolution or "1K", 1290)
            return Cost(per_token * tokens, "heuristic", f"≈{tokens} tokens por imagem")
    return Cost(None, "unavailable", "sem preço publicado; custo real após a 1ª imagem")


# ------------------------------------------------------------------ narração


def tts_cost(db: Session, model_id: str, chars: int, seconds: float) -> Cost:
    hist = history_unit_cost(db, model_id, "tts")
    if hist:
        return Cost(hist[0] * chars, "history", f"média real de {hist[1]} narrações")
    info = catalog.model_info(model_id)
    prices = token_prices(info)
    if prices is None:
        return Cost(None, "unavailable", "sem preço publicado; custo real após a 1ª narração")
    p_in, p_out = prices
    audio_out = _f((info or {}).get("pricing", {}).get("audio_output")) or p_out
    if audio_out:
        tokens_out = seconds * AUDIO_TOKENS_PER_SECOND
        return Cost(chars / 4 * p_in + tokens_out * audio_out, "heuristic",
                    f"cobrado por token; ≈{AUDIO_TOKENS_PER_SECOND} tokens/s de áudio")
    return Cost(chars * p_in, "live", "preço por caractere")


# ------------------------------------------------------------------ vídeo

_RES_RX = re.compile(r"(?<![a-z0-9])(\d{3,4}p|[124]k)(?![a-z0-9])")


def _sku_dims(key: str) -> dict[str, Any]:
    k = key.lower().replace("-", "_")
    res = _RES_RX.search(k)
    dims: dict[str, Any] = {
        "resolution": res.group(1).upper() if res and res.group(1).endswith("k") else (res.group(1) if res else None),
        "audio": True if "with_audio" in k else (False if ("without_audio" in k or "no_audio" in k) else None),
        "video_input": "with_video_input" in k or "video_input" in k,
        "mode": "image" if re.match(r"^(image|i2v|img)", k) else ("text" if re.match(r"^(text|t2v)", k) else None),
        "scale": 0.01 if "cent" in k else 1.0,
    }
    if "video_tokens" in k or k.endswith("_tokens") or k == "tokens":
        dims["unit"] = "token"
    elif "minimum" in k:
        dims["unit"] = "minimum"
    elif "image_input" in k or "reference" in k or "megapixel" in k:
        dims["unit"] = "extra"
    elif "second" in k or "duration" in k:
        dims["unit"] = "second"
    elif "per_video" in k or "per_generation" in k or k in ("video", "request"):
        dims["unit"] = "video"
    else:
        dims["unit"] = None
    return dims


def video_skus_cost(skus: dict[str, Any], *, resolution: str | None, duration: float,
                    with_audio: bool = False, image_input: bool = False) -> tuple[float | None, str]:
    """Custo de um clipe a partir dos `pricing_skus` do /videos/models."""
    parsed = []
    minimum = 0.0
    for key, raw in (skus or {}).items():
        value = _f(raw)
        if value is None:
            continue
        d = _sku_dims(key)
        price = value * d["scale"]
        if d["unit"] == "minimum":
            minimum = max(minimum, price)
            continue
        if d["unit"] not in ("second", "token", "video") or d["video_input"]:
            continue
        if d["resolution"] and resolution and d["resolution"].lower() != resolution.lower():
            continue
        if d["audio"] is not None and d["audio"] != with_audio:
            continue
        if d["mode"] and d["mode"] != ("image" if image_input else "text"):
            continue
        specificity = sum(x is not None for x in (d["resolution"], d["audio"], d["mode"]))
        parsed.append((specificity, d["unit"], price, key))
    if not parsed:
        return None, "sem SKU de preço compatível"
    best_spec = max(p[0] for p in parsed)
    best = [p for p in parsed if p[0] == best_spec]
    units = {p[1] for p in best}
    unit = "second" if "second" in units else ("video" if "video" in units else "token")
    prices = [p[2] for p in best if p[1] == unit]
    price = max(prices)
    note = "" if len(set(prices)) == 1 else "SKUs ambíguos; usado o maior preço"
    if unit == "second":
        cost = price * duration
    elif unit == "video":
        cost = price
    else:
        w, h = RES_DIMS.get(resolution or "720p", (1280, 720))
        cost = price * (w * h * VIDEO_TOKEN_FPS * duration) / 1024
        note = (note + "; " if note else "") + "tokens de vídeo estimados (24 fps)"
    return max(cost, minimum), note


def video_duration_for(model: dict[str, Any] | None, wanted: float) -> int:
    """Menor duração suportada que cobre a cena (ou a maior disponível)."""
    durations = sorted(int(d) for d in ((model or {}).get("supported_durations") or []) if d)
    if not durations:
        return max(2, min(10, round(wanted)))
    for d in durations:
        if d >= wanted - 0.25:
            return d
    return durations[-1]


def video_resolution_for(model: dict[str, Any] | None, wanted: str) -> str | None:
    options = [str(r) for r in ((model or {}).get("supported_resolutions") or [])]
    if not options:
        return wanted
    if wanted in options:
        return wanted
    order = ["360p", "480p", "720p", "768p", "1080p", "1K", "2K", "4K"]
    rank = {r: i for i, r in enumerate(order)}
    target = rank.get(wanted, 2)
    return min(options, key=lambda r: abs(rank.get(r, 2) - target))


def video_cost(db: Session, model_id: str, resolution: str | None, duration: float, *, image_input: bool) -> Cost:
    hist = history_unit_cost(db, model_id, "video", meta_key="resolution", meta_value=resolution)
    if hist:
        return Cost(hist[0] * duration, "history", f"média real de {hist[1]} vídeos")
    info = catalog.video_model(model_id)
    if not info:
        return Cost(None, "unavailable", "modelo de vídeo fora do catálogo")
    cost, note = video_skus_cost(info.get("pricing_skus") or {}, resolution=resolution, duration=duration,
                                 image_input=image_input)
    if cost is None:
        return Cost(None, "unavailable", note)
    return Cost(cost, "live", note)
