"""Estimativa de custo por nível (ECONOMY / BALANCED / PREMIUM) e plano dentro do teto por vídeo.

Preços: catálogo real da OpenRouter (ou média dos custos reais já cobrados aqui).
Quantidades: medidas no projeto (palavras, cenas, tipos) ou derivadas da duração alvo.

Teto por vídeo (em reais, por nível): se o plano padrão passa do teto, o planejador corta primeiro o
vídeo IA, depois alonga as cenas (menos imagens) e, por fim, troca o modelo de imagem pelo do nível
abaixo — até caber. O plano escolhido é o que a produção usa de fato (não só a estimativa).
"""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import catalog, fx, pricing, tiers
from ..models import Asset, AssetKind, AssetType, Project, Quality
from ..providers.registry import split_ref
from . import text
from .common import effective_scene_seconds
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
    # cenas de vídeo IA já planejadas, em ordem: {"id", "duration", "locked"}
    video_scenes: list[dict[str, Any]]


def _base(db: Session, project: Project, *, ignore_scenes: bool = False) -> Base:
    inputs = project_inputs(db, project, ignore_scenes=ignore_scenes)
    return Base(
        project=project, inputs=inputs,
        ctx_tokens=_tokens(len(full_context(db, project)), "en"),
        script_tokens=_tokens(inputs["chars"], project.channel.language),
        prices=Prices(db), tier_cfg=tiers.get_tier_settings(db), fx=fx.get_rate(db),
        video_scenes=[] if ignore_scenes else [
            {"id": s.id, "duration": s.duration, "locked": bool(s.locked)}
            for s in project.scenes if s.asset_type == AssetType.VIDEO.value
        ],
    )


LINE_ORDER = ("script", "scenes", "images", "videos", "motion", "narration", "thumb_concepts", "thumb_images",
              "metadata", "learning")


# ------------------------------------------------------------------ componentes do custo
# Cada componente depende só das suas escolhas; o planejador combina componentes já calculados.


def _text_lines(b: Base, text_model: str | None, n: int) -> dict[str, dict[str, Any]]:
    inputs, prices = b.inputs, b.prices
    blocks = max(1, math.ceil(inputs["words"] / 650))
    out = {
        "script": _llm_line(prices, "script", "script", "Análise do roteiro", text_model,
                            b.ctx_tokens + b.script_tokens + PROMPT_OVERHEAD, 3200),
        "scenes": _llm_line(prices, "scenes", "scenes", f"Divisão em {n} cenas ({blocks} blocos)", text_model,
                            blocks * (b.ctx_tokens + PROMPT_OVERHEAD) + int(b.script_tokens * 1.15) + 200 * blocks,
                            0, units=n, per_unit_default=190),
        "metadata": _llm_line(prices, "metadata", "metadata", "Título, descrição e tags", text_model,
                              b.ctx_tokens + b.script_tokens + PROMPT_OVERHEAD + n * 22, 2600),
    }
    if b.project.channel.auto_learn:
        out["learning"] = _llm_line(prices, "learning", "learning", "Aprendizados para a Skill", text_model,
                                    b.ctx_tokens + PROMPT_OVERHEAD + 1500, 900)
    return out


def _image_lines(b: Base, model: str | None, resolution: str | None, n: int) -> dict[str, dict[str, Any]]:
    unit = b.prices.image(model, resolution)
    cost = pricing.Cost(unit.value * n, unit.source, unit.note) if unit and unit.value is not None else unit
    return {"images": _line("images", "visuals", f"Imagens das cenas ({n} × {resolution})", model, n, "imagens", cost)}


def _video_lines(b: Base, tier: str, model: str | None, video_secs: list[float], n: int) -> dict[str, dict[str, Any]]:
    if video_secs:
        vinfo = b.prices.video_info(model)
        res = pricing.video_resolution_for(vinfo, b.tier_cfg[tier].get("video_resolution") or "720p")
        total, src, note, ok = 0.0, "live", "", True
        for secs in video_secs:
            c = b.prices.video(model, res, pricing.video_duration_for(vinfo, secs)) if model else None
            if c is None or c.value is None:
                ok, note = False, (c.note if c else "sem modelo de vídeo")
                break
            total += c.value
            src, note = c.source, c.note
        videos = _line("videos", "visuals", f"Vídeos IA ({len(video_secs)} cenas, {res})", model, len(video_secs),
                       "clipes", pricing.Cost(total if ok else None, src if ok else "unavailable", note))
    else:
        videos = _line("videos", "visuals", "Vídeos IA (nenhuma cena)", None, 0, "clipes",
                       pricing.Cost(0.0, "free", "nenhuma cena com vídeo IA neste plano"))
    motion_n = n - len(video_secs)
    motion = _line("motion", "visuals", f"Movimento local ({motion_n} cenas)", "ffmpeg (local)", motion_n, "clipes",
                   pricing.Cost(0.0, "free", "renderizado no servidor"))
    return {"videos": videos, "motion": motion}


def _tts_lines(b: Base, model: str | None) -> dict[str, dict[str, Any]]:
    chars = b.inputs["narration_chars"]
    cost = b.prices.tts(model, chars, b.inputs["seconds"]) if model else None
    return {"narration": _line("narration", "narration", f"Narração ({chars:,} caracteres)".replace(",", "."),
                               model, chars, "caracteres", cost)}


def _thumb_lines(b: Base, text_model: str | None, option: tuple) -> dict[str, dict[str, Any]]:
    model, resolution, concepts, variations = option
    unit = b.prices.image(model, resolution)
    imgs = concepts * variations
    cost = pricing.Cost(unit.value * imgs, unit.source, unit.note) if unit and unit.value is not None else unit
    return {
        "thumb_concepts": _llm_line(b.prices, "thumb_concepts", "thumbnail", f"Conceitos de thumbnail ({concepts})",
                                    text_model, b.ctx_tokens + PROMPT_OVERHEAD + 900, 0, units=concepts,
                                    per_unit_default=380),
        "thumb_images": _line("thumb_images", "thumbnail", f"Imagens de thumbnail ({concepts} × {variations})", model,
                              imgs, "imagens", cost),
    }


def _sum(lines: dict[str, dict[str, Any]]) -> tuple[float, bool]:
    known = [ln["cost"] for ln in lines.values() if ln["cost"] is not None]
    return sum(known), len(known) == len(lines)


# ------------------------------------------------------------------ opções de cada componente


def _lower_tiers(tier: str) -> list[str]:
    return TIER_ORDER[TIER_ORDER.index(tier) + 1:]


def _cheaper_chain(first: Any, others: list[Any], price) -> list[Any]:
    """[escolha do nível] + opções dos níveis abaixo, só as que custam menos que a anterior."""
    chain = [first]
    for item in others:
        if item is None or item in chain:
            continue
        p, prev = price(item), price(chain[-1])
        if p is not None and (prev is None or p < prev):
            chain.append(item)
    return chain


def _text_price(model: str | None) -> float | None:
    p = pricing.token_prices(catalog.model_info(split_ref(model)[1])) if model else None
    return None if p is None else p[0] * 3 + p[1]


@dataclass
class Options:
    images: list[tuple[str | None, str | None]]
    texts: list[str | None]
    tts: list[str | None]
    thumbs: list[tuple[str | None, str | None, int, int]]
    secs: list[float | None]  # None = cenas já planejadas
    videos: list[float]  # % de vídeo (sem cenas) ou quantas cenas de vídeo planejadas manter
    base_secs: float | None


def _options(db: Session, b: Base, tier: str, models: dict[str, str | None], pins: dict[str, str]) -> Options:
    cfg, all_cfg, prices, channel = b.tier_cfg[tier], b.tier_cfg, b.prices, b.project.channel

    def resolved(op: str, t: str) -> str | None:
        return tiers.resolve_model(db, op, t, settings=all_cfg).model

    lower = _lower_tiers(tier)
    # imagem (modelo fixado em Configurações não é trocado)
    images = [(models["image"], cfg.get("image_resolution"))]
    if not cfg.get("image"):
        images = _cheaper_chain(images[0], [(resolved("image", t), all_cfg[t].get("image_resolution")) for t in lower],
                                lambda o: (c.value if (c := prices.image(*o)) else None))
    # texto
    texts = [models["text"]]
    if not cfg.get("text"):
        texts = _cheaper_chain(texts[0], [resolved("text", t) for t in lower], _text_price)
    # narração (a voz do canal, se fixada, não é trocada)
    tts_first = channel.tts_model or models["tts"]
    tts_list = [tts_first]
    if not channel.tts_model and not cfg.get("tts"):
        chars, secs = b.inputs["narration_chars"], b.inputs["seconds"]
        tts_list = _cheaper_chain(tts_first, [resolved("tts", t) for t in lower],
                                  lambda m: (c.value if m and (c := prices.tts(m, chars, secs)) else None))
    # thumbnails: menos variações, depois o modelo/quantidade dos níveis abaixo
    concepts, variations = int(cfg.get("thumb_concepts") or 3), int(cfg.get("thumb_variations") or 1)
    first = (models["thumbnail"], cfg.get("image_resolution"), concepts, variations)
    others: list[tuple] = [(first[0], first[1], concepts, 1)]
    if not cfg.get("thumbnail"):
        others += [(resolved("thumbnail", t), all_cfg[t].get("image_resolution"),
                    min(concepts, int(all_cfg[t].get("thumb_concepts") or 2)), 1) for t in lower]

    def thumb_price(o: tuple) -> float | None:
        c = prices.image(o[0], o[1])
        return None if c is None or c.value is None else c.value * o[2] * o[3]

    thumbs = _cheaper_chain(first, others, thumb_price)
    # o que já foi gerado com um modelo continua com ele (mesma voz e mesmo estilo em todas as cenas)
    for key, chain in (("image", images), ("tts", tts_list)):
        pin = pins.get(key)
        if pin:
            match = [o for o in chain if (o[0] if isinstance(o, tuple) else o) == pin]
            if match:
                chain[:] = match
    # cenas e vídeo
    if b.inputs["scenes_planned"]:
        planned = len(b.video_scenes)
        locked = sum(1 for v in b.video_scenes if v["locked"])
        return Options(images, texts, tts_list, thumbs, [None],
                       sorted({planned, max(locked, planned // 2), locked}, reverse=True), None)
    base = effective_scene_seconds(channel, cfg)
    soft = [base] + [s for s in SOFT_SCENE_SECONDS if s > base]
    secs = soft + [s for s in HARD_SCENE_SECONDS if s > soft[-1]]
    share = float(cfg.get("video_share") or 0)
    return Options(images, texts, tts_list, thumbs, secs, sorted({share, round(share / 2, 4), 0.0}, reverse=True), base)


# ------------------------------------------------------------------ planejador


@dataclass(frozen=True)
class Choice:
    img: int = 0
    text: int = 0
    tts: int = 0
    thumb: int = 0
    secs: int = 0
    video: int = 0


# quanto cada redução pesa na qualidade percebida (menor = cortado antes)
PENALTY = {"video": 2.0, "thumb": 1.0, "text": 2.5, "sec": 0.7, "img": 4.0, "tts": 5.0}


class Planner:
    def __init__(self, db: Session, b: Base, tier: str, pins: dict[str, str] | None = None) -> None:
        self.db, self.b, self.tier = db, b, tier
        self.models = {op: tiers.resolve_model(db, op, tier, settings=b.tier_cfg).model for op in tiers.OPERATIONS}
        self.opt = _options(db, b, tier, self.models, pins or {})
        self._memo: dict[tuple, Any] = {}

    def _get(self, key: tuple, fn):
        if key not in self._memo:
            self._memo[key] = fn()
        return self._memo[key]

    def scenes(self, c: Choice) -> tuple[int, float]:
        secs = self.opt.secs[c.secs]
        inputs = self.b.inputs
        if secs is None:
            return inputs["scenes"], inputs["avg_scene_seconds"]
        n = max(1, round(inputs["seconds"] / secs))
        return n, inputs["seconds"] / n

    def video_secs(self, c: Choice) -> list[float]:
        n, avg = self.scenes(c)
        value = self.opt.videos[c.video]
        if self.opt.secs[c.secs] is None:
            # mantém as travadas e as primeiras; as demais viram imagem com movimento
            keep = int(value)
            locked = [v for v in self.b.video_scenes if v["locked"]]
            free = [v for v in self.b.video_scenes if not v["locked"]][:max(0, keep - len(locked))]
            return [v["duration"] for v in locked + free]
        return [avg] * int(round(n * value))

    def components(self, c: Choice) -> list[dict[str, dict[str, Any]]]:
        b, o = self.b, self.opt
        n, _ = self.scenes(c)
        text_model = o.texts[c.text]
        return [
            self._get(("text", c.text, n), lambda: _text_lines(b, text_model, n)),
            self._get(("img", c.img, n), lambda: _image_lines(b, *o.images[c.img], n)),
            self._get(("video", c.video, c.secs), lambda: _video_lines(b, self.tier, self.models["video"],
                                                                       self.video_secs(c), n)),
            self._get(("tts", c.tts), lambda: _tts_lines(b, o.tts[c.tts])),
            self._get(("thumb", c.thumb, c.text), lambda: _thumb_lines(b, text_model, o.thumbs[c.thumb])),
        ]

    def cost(self, c: Choice) -> tuple[float, bool]:
        total, complete = 0.0, True
        for comp in self.components(c):
            t, ok = self._get(("sum", id(comp)), lambda comp=comp: _sum(comp))
            total += t
            complete = complete and ok
        return total, complete

    def penalty(self, c: Choice) -> float:
        o = self.opt
        p = PENALTY["thumb"] * c.thumb + PENALTY["text"] * c.text + PENALTY["img"] * c.img + PENALTY["tts"] * c.tts
        if o.videos and o.videos[0]:
            p += PENALTY["video"] * (1 - o.videos[c.video] / o.videos[0])
        if o.base_secs is not None:
            p += PENALTY["sec"] * (o.secs[c.secs] - o.base_secs)
        return p

    def choices(self) -> list[Choice]:
        o = self.opt
        return [Choice(*idx) for idx in itertools.product(
            range(len(o.images)), range(len(o.texts)), range(len(o.tts)), range(len(o.thumbs)),
            range(len(o.secs)), range(len(o.videos)))]

    def lines(self, c: Choice) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for comp in self.components(c):
            merged.update(comp)
        return [merged[k] for k in LINE_ORDER if k in merged]

    def adjustments(self, c: Choice) -> list[str]:
        o, base = self.opt, Choice()
        notes = []
        n0, _ = self.scenes(base)
        n, _ = self.scenes(c)
        v0, v = len(self.video_secs(base)), len(self.video_secs(c))
        if v < v0:
            if o.secs[c.secs] is None:
                notes.append(f"vídeo IA em {v} das {v0} cenas planejadas (as outras viram imagem com movimento)")
            else:
                notes.append(f"vídeo IA: {v} cenas em vez de {v0}" if v else f"sem vídeo IA (seriam {v0} cenas)")
        if o.secs[c.secs] is not None and c.secs:
            notes.append(f"cenas de ~{o.secs[c.secs]:g} s em vez de {o.secs[0]:g} s ({n0} → {n} imagens)")
        if c.img:
            notes.append(f"imagem: {_short(o.images[c.img][0])} em vez de {_short(o.images[0][0])}")
        if c.thumb:
            t0, t = o.thumbs[0], o.thumbs[c.thumb]
            notes.append(f"thumbnails: {t[2]} × {t[3]}" + (f" com {_short(t[0])}" if t[0] != t0[0] else "")
                         + f" em vez de {t0[2]} × {t0[3]}")
        if c.text:
            notes.append(f"texto: {_short(o.texts[c.text])} em vez de {_short(o.texts[0])}")
        if c.tts:
            notes.append(f"narração: {_short(o.tts[c.tts])} em vez de {_short(o.tts[0])}")
        return notes


def fit_tier(db: Session, b: Base, tier: str, pins: dict[str, str] | None = None) -> dict[str, Any]:
    """Escolhe o plano de melhor qualidade que cabe no teto do nível e devolve a estimativa dele."""
    cfg = b.tier_cfg[tier]
    rate = float(b.fx["rate"])
    cap_brl = float(cfg.get("cap_brl") or 0) or None
    cap_usd = cap_brl / rate if cap_brl else None
    planner = Planner(db, b, tier, pins)
    chosen, fits = Choice(), None
    if cap_usd:
        options = [(c, *planner.cost(c)) for c in planner.choices()]
        fitting = [(planner.penalty(c), total, c) for c, total, ok in options if ok and total <= cap_usd]
        if fitting:
            chosen, fits = min(fitting, key=lambda x: (x[0], x[1]))[2], True
        else:
            chosen, fits = min(options, key=lambda x: x[1])[0], False
    total, complete = planner.cost(chosen)
    lines = planner.lines(chosen)
    adjustments = planner.adjustments(chosen)
    if fits is False:
        adjustments.append("mesmo no plano mais enxuto passa do teto" + (
            " (cenas travadas com vídeo IA continuam)" if b.inputs["scenes_planned"] else ""))
    o = planner.opt
    n, _ = planner.scenes(chosen)
    image_model, image_res = o.images[chosen.img]
    thumb = o.thumbs[chosen.thumb]
    secs = o.secs[chosen.secs]
    models = {**planner.models, "image": image_model, "text": o.texts[chosen.text], "tts": o.tts[chosen.tts],
              "thumbnail": thumb[0]}
    return {
        "scenes": n,
        "total": round(total, 4),
        "total_brl": round(total * rate, 2),
        "complete": complete,
        "missing": [ln["label"] for ln in lines if ln["cost"] is None],
        "lines": lines,
        "models": models,
        "cap_brl": cap_brl,
        "cap_usd": round(cap_usd, 4) if cap_usd else None,
        "fits": fits,
        "adjustments": adjustments,
        "plan": {
            "tier": tier, "scene_seconds": secs, "scenes": n,
            "video_share": o.videos[chosen.video] if secs is not None else None,
            "video_keep": int(o.videos[chosen.video]) if secs is None else None,
            "image_model": image_model, "image_resolution": image_res,
            "text_model": o.texts[chosen.text], "tts_model": o.tts[chosen.tts],
            "thumb_model": thumb[0], "thumb_resolution": thumb[1], "thumb_concepts": thumb[2],
            "thumb_variations": thumb[3],
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
    plan = fit_tier(db, _base(db, project, ignore_scenes=ignore_scenes), tier, pins=_pins(db, project, stored))["plan"]
    plan["cfg"] = cfg_hash
    project.plan = plan
    return plan


def _pins(db: Session, project: Project, stored: dict[str, Any]) -> dict[str, str]:
    """Modelos que já geraram imagens/narração neste nível continuam (mesmo estilo e mesma voz)."""
    if stored.get("tier") != project.quality:
        return {}
    pins = {}
    for key, field, kind in (("image", "image_model", AssetKind.IMAGE.value), ("tts", "tts_model", AssetKind.AUDIO.value)):
        model = stored.get(field)
        if model and db.scalar(select(Asset.id).where(Asset.project_id == project.id, Asset.kind == kind,
                                                      Asset.model == split_ref(model)[1]).limit(1)):
            pins[key] = model
    return pins


PLAN_KEYS = {"text": "text_model", "image": "image_model", "tts": "tts_model", "thumbnail": "thumb_model"}


def plan_model(db: Session, project: Project, op: str) -> str:
    """Modelo que o plano do projeto (dentro do teto) usa nesta operação."""
    from .common import model_for

    return production_plan(db, project).get(PLAN_KEYS[op]) or model_for(db, op, project.quality)


def planned(project: Project, key: str) -> Any:
    """Valor do plano gravado, se ele vale para o nível atual do projeto (sem recalcular)."""
    plan = project.plan or {}
    return plan.get(key) if plan.get("tier") == project.quality else None
