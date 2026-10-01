"""Estimativa de custo por nível (ECONOMY / BALANCED / PREMIUM) e plano dentro do teto por vídeo.

Preços: catálogo real da OpenRouter (ou média dos custos reais já cobrados aqui).
Quantidades: medidas no projeto (palavras, cenas, tipos) ou derivadas da duração alvo.

Teto por vídeo (em reais, por nível): se o plano padrão passa do teto, o planejador corta primeiro o
vídeo IA, depois alonga as cenas (menos imagens) e, por fim, troca o modelo de imagem pelo do nível
abaixo — até caber. O plano escolhido é o que a produção usa de fato (não só a estimativa).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from .. import catalog, fx, pricing, tiers
from ..models import AssetType, Project, Quality
from ..providers.registry import split_ref
from . import text
from .common import effective_scene_seconds, tts_settings
from .context import full_context

CHARS_PER_TOKEN = {"en": 4.0, "pt": 3.6, "es": 3.6, "fr": 3.6, "it": 3.6, "de": 3.5, "nl": 3.6, "pl": 3.0,
                   "cs": 3.0, "sk": 3.0, "ru": 3.0, "uk": 3.0, "ja": 1.5, "zh": 1.4, "ko": 1.6}
PROMPT_OVERHEAD = 1200  # instruções fixas de cada chamada (tokens)
# durações de cena que o planejador tenta para caber no teto: primeiro até 12 s com o modelo de imagem
# do nível; só depois do modelo mais barato, cenas ainda mais longas
SOFT_SCENE_SECONDS = (9.0, 12.0)
HARD_SCENE_SECONDS = (15.0, 18.0, 20.0)
TIER_ORDER = [Quality.PREMIUM.value, Quality.BALANCED.value, Quality.ECONOMY.value]


def _tokens(chars: int, lang: str) -> int:
    return int(math.ceil(chars / CHARS_PER_TOKEN.get(text.lang_base(lang), 3.5)))


def _short(model: str | None) -> str:
    return split_ref(model)[1].split("/")[-1] if model else "—"


class Prices:
    """Memoriza as consultas de preço de um cálculo (o ajuste ao teto testa várias combinações)."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._memo: dict[tuple, Any] = {}

    def _get(self, key: tuple, fn):
        if key not in self._memo:
            self._memo[key] = fn()
        return self._memo[key]

    def history_tokens(self, stage: str, model: str) -> dict[str, float] | None:
        return self._get(("tokens", stage, model), lambda: pricing.history_tokens(self.db, stage, model)
                         or pricing.history_tokens(self.db, stage))

    def llm(self, model: str, tokens_in: int, tokens_out: int) -> pricing.Cost:
        return pricing.llm_cost(split_ref(model)[1], tokens_in, tokens_out)

    def image(self, model: str | None, resolution: str | None) -> pricing.Cost | None:
        if not model:
            return None
        return self._get(("image", model, resolution),
                         lambda: pricing.image_cost(self.db, split_ref(model)[1], resolution))

    def video_info(self, model: str | None) -> dict[str, Any] | None:
        return self._get(("vinfo", model), lambda: catalog.video_model(split_ref(model)[1]) if model else None)

    def video(self, model: str, resolution: str | None, duration: int) -> pricing.Cost:
        return self._get(("video", model, resolution, duration), lambda: pricing.video_cost(
            self.db, split_ref(model)[1], resolution, duration, image_input=True))

    def tts(self, model: str, chars: int, seconds: float) -> pricing.Cost:
        return self._get(("tts", model, chars, round(seconds)),
                         lambda: pricing.tts_cost(self.db, split_ref(model)[1], chars, seconds))


def _line(key: str, stage: str, label: str, model: str | None, quantity: float, unit: str,
          cost: pricing.Cost | None, tokens_in: int | None = None, tokens_out: int | None = None) -> dict[str, Any]:
    return {
        "key": key, "stage": stage, "label": label, "model": model, "quantity": round(quantity, 2), "unit": unit,
        "cost": None if cost is None or cost.value is None else round(cost.value, 6),
        "source": cost.source if cost else "unavailable", "note": cost.note if cost else "",
        "tokens_in": tokens_in, "tokens_out": tokens_out,
    }


def _llm_line(prices: Prices, key: str, stage: str, label: str, model: str | None, tokens_in: int,
              default_out: int, *, units: float | None = None, per_unit_default: int | None = None) -> dict[str, Any]:
    if not model:
        return _line(key, stage, label, None, 1, "chamada", pricing.Cost(None, "unavailable", "sem modelo de texto"))
    hist = prices.history_tokens(stage, model)
    if units and per_unit_default:
        per_unit = (hist or {}).get("completion_per_unit") or per_unit_default
        tokens_out = int(units * per_unit)
    else:
        tokens_out = int((hist or {}).get("completion") or default_out)
    cost = prices.llm(model, tokens_in, tokens_out)
    if cost.value is not None and cost.source == "live":
        cost.note = "tokens calibrados pelo histórico" if hist else "tokens estimados pelo tamanho do texto"
        if hist:
            cost.source = "history"
    return _line(key, stage, label, model, 1, "etapa", cost, tokens_in, tokens_out)


def project_inputs(db: Session, project: Project, *, ignore_scenes: bool = False) -> dict[str, Any]:
    channel = project.channel
    wpm = channel.words_per_minute or text.default_wpm(channel.language)
    script = project.script or ""
    words = text.word_count(script)
    chars = len(script)
    from_target = words < 30
    if from_target:
        minutes = project.target_minutes or (channel.duration_min + channel.duration_max) / 2
        words = int(minutes * wpm)
        chars = int(words * 6.2)
    minutes = words / wpm
    scenes = [] if ignore_scenes else list(project.scenes)
    if scenes:
        n = len(scenes)
        seconds = [s.duration for s in scenes]
        video_secs = [s.duration for s in scenes if s.asset_type == AssetType.VIDEO.value]
        narr_chars = sum(len(s.narration) for s in scenes)
    else:
        n = max(1, round(minutes * 60 / (channel.scene_seconds or 7.0)))
        seconds = [minutes * 60 / n] * n
        video_secs = None
        narr_chars = chars
    # sem cenas planejadas, a quantidade de cenas depende do nível (ver _scene_options)
    return {
        "words": words, "chars": chars, "minutes": round(minutes, 2), "scenes": n, "seconds": sum(seconds),
        "avg_scene_seconds": sum(seconds) / n if n else 0, "video_secs": video_secs, "narration_chars": narr_chars,
        "from_target": from_target, "scenes_planned": bool(scenes), "language": channel.language,
    }


@dataclass
class Base:
    """O que não muda entre os níveis de um mesmo projeto."""

    project: Project
    inputs: dict[str, Any]
    ctx_tokens: int
    script_tokens: int
    prices: Prices
    tier_cfg: dict[str, dict[str, Any]]
    fx: dict[str, Any]


def _base(db: Session, project: Project, *, ignore_scenes: bool = False) -> Base:
    inputs = project_inputs(db, project, ignore_scenes=ignore_scenes)
    return Base(
        project=project, inputs=inputs,
        ctx_tokens=_tokens(len(full_context(db, project)), "en"),
        script_tokens=_tokens(inputs["chars"], project.channel.language),
        prices=Prices(db), tier_cfg=tiers.get_tier_settings(db), fx=fx.get_rate(db),
    )


def _lines(db: Session, b: Base, tier: str, models: dict[str, str | None], *, n: int, avg_secs: float,
           video_secs: list[float], image_model: str | None, image_resolution: str | None) -> list[dict[str, Any]]:
    cfg = b.tier_cfg[tier]
    inputs, prices, channel = b.inputs, b.prices, b.project.channel
    lines: list[dict[str, Any]] = []
    text_model = models["text"]
    # 1 roteiro
    lines.append(_llm_line(prices, "script", "script", "Análise do roteiro", text_model,
                           b.ctx_tokens + b.script_tokens + PROMPT_OVERHEAD, 3200))
    # 2 cenas
    blocks = max(1, math.ceil(inputs["words"] / 650))
    lines.append(_llm_line(prices, "scenes", "scenes", f"Divisão em {n} cenas ({blocks} blocos)", text_model,
                           blocks * (b.ctx_tokens + PROMPT_OVERHEAD) + int(b.script_tokens * 1.15) + 200 * blocks,
                           0, units=n, per_unit_default=170))
    # 3 visuais
    unit = prices.image(image_model, image_resolution)
    img_cost = pricing.Cost(unit.value * n, unit.source, unit.note) if unit and unit.value is not None else unit
    lines.append(_line("images", "visuals", f"Imagens das cenas ({n} × {image_resolution})", image_model, n,
                       "imagens", img_cost))
    vmodel = models["video"]
    if video_secs:
        vinfo = prices.video_info(vmodel)
        res = pricing.video_resolution_for(vinfo, cfg.get("video_resolution") or "720p")
        total_v, src, note, ok = 0.0, "live", "", True
        for secs in video_secs:
            c = prices.video(vmodel, res, pricing.video_duration_for(vinfo, secs)) if vmodel else None
            if c is None or c.value is None:
                ok, note = False, (c.note if c else "sem modelo de vídeo")
                break
            total_v += c.value
            src, note = c.source, c.note
        lines.append(_line("videos", "visuals", f"Vídeos IA ({len(video_secs)} cenas, {res})", vmodel, len(video_secs),
                           "clipes", pricing.Cost(total_v if ok else None, src if ok else "unavailable", note)))
    else:
        lines.append(_line("videos", "visuals", "Vídeos IA (nenhuma cena)", None, 0, "clipes",
                           pricing.Cost(0.0, "free", "nenhuma cena com vídeo IA neste plano")))
    motion_n = n - len(video_secs)
    lines.append(_line("motion", "visuals", f"Movimento local ({motion_n} cenas)", "ffmpeg (local)", motion_n, "clipes",
                       pricing.Cost(0.0, "free", "renderizado no servidor")))
    # 4 narração
    try:
        tts_model = tts_settings(db, channel, tier)["model"]
    except Exception:  # noqa: BLE001 - sem modelo de TTS disponível
        tts_model = None
    tts_cost = prices.tts(tts_model, inputs["narration_chars"], inputs["seconds"]) if tts_model else None
    lines.append(_line("narration", "narration", f"Narração ({inputs['narration_chars']:,} caracteres)".replace(",", "."),
                       tts_model, inputs["narration_chars"], "caracteres", tts_cost))
    # 5 thumbnail
    concepts = int(cfg.get("thumb_concepts") or 3)
    variations = int(cfg.get("thumb_variations") or 1)
    lines.append(_llm_line(prices, "thumb_concepts", "thumbnail", f"Conceitos de thumbnail ({concepts})", text_model,
                           b.ctx_tokens + PROMPT_OVERHEAD + 900, 0, units=concepts, per_unit_default=380))
    th_model = models["thumbnail"]
    th_unit = prices.image(th_model, cfg.get("image_resolution"))
    imgs = concepts * variations
    th_cost = pricing.Cost(th_unit.value * imgs, th_unit.source, th_unit.note) if th_unit and th_unit.value is not None else th_unit
    lines.append(_line("thumb_images", "thumbnail", f"Imagens de thumbnail ({concepts} × {variations})", th_model, imgs,
                       "imagens", th_cost))
    # 6 metadados
    lines.append(_llm_line(prices, "metadata", "metadata", "Título, descrição e tags", text_model,
                           b.ctx_tokens + b.script_tokens + PROMPT_OVERHEAD + n * 22, 2600))
    # 7 aprendizado
    if channel.auto_learn:
        lines.append(_llm_line(prices, "learning", "learning", "Aprendizados para a Skill", text_model,
                               b.ctx_tokens + PROMPT_OVERHEAD + 1500, 900))
    return lines


def _image_chain(db: Session, b: Base, tier: str, models: dict[str, str | None]) -> list[tuple[str | None, str | None]]:
    """Modelo de imagem do nível e, se não foi fixado por você, os dos níveis abaixo (só se mais baratos)."""
    cfg = b.tier_cfg[tier]
    chain = [(models["image"], cfg.get("image_resolution"))]
    if cfg.get("image"):
        return chain  # modelo fixado em Configurações: não é trocado
    for lower in TIER_ORDER[TIER_ORDER.index(tier) + 1:]:
        m = tiers.resolve_model(db, "image", lower, settings=b.tier_cfg).model
        res = b.tier_cfg[lower].get("image_resolution")
        if not m:
            continue
        cost = b.prices.image(m, res)
        prev = b.prices.image(*chain[-1])
        if cost and cost.value is not None and (prev is None or prev.value is None or cost.value < prev.value):
            chain.append((m, res))
    return chain


def _candidates(b: Base, tier: str, chain: list) -> list[dict[str, Any]]:
    """Planos em ordem de preferência (do mais completo ao mais enxuto)."""
    cfg = b.tier_cfg[tier]
    inputs = b.inputs
    if inputs["scenes_planned"]:
        # cenas já existem: só o modelo de imagem pode mudar
        fixed = {"secs": None, "share": None}
        return [{**fixed, "img": i} for i in range(len(chain))]
    base_secs = effective_scene_seconds(b.project.channel, cfg)
    soft = [base_secs] + [s for s in SOFT_SCENE_SECONDS if s > base_secs]
    hard = [s for s in HARD_SCENE_SECONDS if s > soft[-1]]
    share = float(cfg.get("video_share") or 0)
    shares = sorted({share, round(share / 2, 4), 0.0}, reverse=True)
    seq = [{"img": 0, "secs": soft[0], "share": s} for s in shares]
    seq += [{"img": 0, "secs": s, "share": 0.0} for s in soft[1:]]
    for i in range(1, len(chain)):
        seq += [{"img": i, "secs": s, "share": 0.0} for s in soft]
    seq += [{"img": len(chain) - 1, "secs": s, "share": 0.0} for s in hard]
    return seq


def _evaluate(db: Session, b: Base, tier: str, models: dict, chain: list, cand: dict) -> dict[str, Any]:
    inputs = b.inputs
    if cand["secs"] is None:
        n, avg = inputs["scenes"], inputs["avg_scene_seconds"]
        video_secs = list(inputs["video_secs"] or [])
    else:
        n = max(1, round(inputs["seconds"] / cand["secs"]))
        avg = inputs["seconds"] / n
        video_secs = [avg] * int(round(n * cand["share"]))
    image_model, image_res = chain[cand["img"]]
    lines = _lines(db, b, tier, models, n=n, avg_secs=avg, video_secs=video_secs,
                   image_model=image_model, image_resolution=image_res)
    priced = [ln for ln in lines if ln["cost"] is not None]
    return {"cand": cand, "n": n, "lines": lines, "total": sum(ln["cost"] for ln in priced),
            "complete": len(priced) == len(lines), "image_model": image_model, "image_resolution": image_res,
            "videos": len(video_secs)}


def _adjustments(b: Base, tier: str, chain: list, first: dict, chosen: dict) -> list[str]:
    notes = []
    c0, c = first["cand"], chosen["cand"]
    if c["share"] is not None and c["share"] < c0["share"]:
        notes.append(f"vídeo IA: {chosen['videos']} cenas em vez de {first['videos']}" if chosen["videos"]
                     else f"sem vídeo IA (seriam {first['videos']} cenas)")
    if c["secs"] is not None and c["secs"] > c0["secs"]:
        notes.append(f"cenas de ~{c['secs']:g} s em vez de {c0['secs']:g} s ({first['n']} → {chosen['n']} imagens)")
    if c["img"] > 0:
        notes.append(f"imagem: {_short(chosen['image_model'])} em vez de {_short(chain[0][0])}")
    return notes


def fit_tier(db: Session, b: Base, tier: str) -> dict[str, Any]:
    """Escolhe o plano mais completo que cabe no teto do nível e devolve a estimativa dele."""
    cfg = b.tier_cfg[tier]
    models = {op: tiers.resolve_model(db, op, tier, settings=b.tier_cfg).model for op in tiers.OPERATIONS}
    rate = float(b.fx["rate"])
    cap_brl = float(cfg.get("cap_brl") or 0) or None
    cap_usd = cap_brl / rate if cap_brl else None
    chain = _image_chain(db, b, tier, models) if cap_usd else [(models["image"], cfg.get("image_resolution"))]
    cands = _candidates(b, tier, chain)
    first = _evaluate(db, b, tier, models, chain, cands[0])
    chosen, fits = first, None
    if cap_usd:
        fits = False
        tried = []
        for cand in cands:
            ev = first if cand is cands[0] else _evaluate(db, b, tier, models, chain, cand)
            tried.append(ev)
            if ev["complete"] and ev["total"] <= cap_usd:
                chosen, fits = ev, True
                break
        if not fits:
            chosen = min(tried, key=lambda e: e["total"])
    adjustments = _adjustments(b, tier, chain, first, chosen)
    if fits is False:
        adjustments.append("as cenas já planejadas passam do teto: replaneje ou troque cenas de vídeo IA por imagem"
                           if b.inputs["scenes_planned"] else "mesmo no plano mais enxuto passa do teto")
    lines = chosen["lines"]
    total = chosen["total"]
    secs = chosen["cand"]["secs"]
    share = chosen["cand"]["share"]
    return {
        "scenes": chosen["n"],
        "total": round(total, 4),
        "total_brl": round(total * rate, 2),
        "complete": chosen["complete"],
        "missing": [ln["label"] for ln in lines if ln["cost"] is None],
        "lines": lines,
        "models": {**models, "image": chosen["image_model"]},
        "cap_brl": cap_brl,
        "cap_usd": round(cap_usd, 4) if cap_usd else None,
        "fits": fits,
        "adjustments": adjustments,
        "plan": {
            "tier": tier, "scene_seconds": secs, "video_share": share, "scenes": chosen["n"],
            "image_model": chosen["image_model"], "image_resolution": chosen["image_resolution"],
            "cap_brl": cap_brl, "total_usd": round(total, 4), "total_brl": round(total * rate, 2),
            "fits": fits, "adjustments": adjustments,
        },
    }


def estimate_project(db: Session, project: Project) -> dict[str, Any]:
    b = _base(db, project)
    result = {tier.value: fit_tier(db, b, tier.value) for tier in Quality}
    return {"inputs": b.inputs, "tiers": result, "current": project.quality, "fx": b.fx,
            "catalog_at": str(catalog.fetched_at(catalog.KINDS["text"]) or "")}


def _cfg_hash(db: Session, tier: str) -> str:
    return text.content_hash(json.dumps(tiers.get_tier_settings(db)[tier], sort_keys=True, default=str))


def production_plan(db: Session, project: Project, *, refresh: bool = False, ignore_scenes: bool = False) -> dict[str, Any]:
    """Plano que a produção segue (modelo de imagem, duração das cenas, % de vídeo).

    Fica gravado no projeto para todas as cenas usarem o mesmo modelo; é refeito ao planejar as cenas,
    ao gerar os visuais em lote, ao trocar o nível do projeto ou ao mudar a configuração do nível.
    """
    tier = project.quality
    cfg_hash = _cfg_hash(db, tier)
    stored = project.plan or {}
    if not refresh and stored.get("tier") == tier and stored.get("cfg") == cfg_hash:
        return stored
    plan = fit_tier(db, _base(db, project, ignore_scenes=ignore_scenes), tier)["plan"]
    plan["cfg"] = cfg_hash
    project.plan = plan
    return plan
