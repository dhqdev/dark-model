"""Estimativa de custo por nível (ECONOMY / BALANCED / PREMIUM) antes de gerar.

Preços: catálogo real da OpenRouter (ou média dos custos reais já cobrados aqui).
Quantidades: medidas no projeto (palavras, cenas, tipos) ou derivadas da duração alvo.
"""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy.orm import Session

from .. import catalog, pricing, tiers
from ..models import AssetType, Project, Quality
from ..providers.registry import split_ref
from . import text
from .common import effective_scene_seconds, tts_settings
from .context import full_context

CHARS_PER_TOKEN = {"en": 4.0, "pt": 3.6, "es": 3.6, "fr": 3.6, "it": 3.6, "de": 3.5, "nl": 3.6, "pl": 3.0,
                   "cs": 3.0, "sk": 3.0, "ru": 3.0, "uk": 3.0, "ja": 1.5, "zh": 1.4, "ko": 1.6}
PROMPT_OVERHEAD = 1200  # instruções fixas de cada chamada (tokens)


def _tokens(chars: int, lang: str) -> int:
    return int(math.ceil(chars / CHARS_PER_TOKEN.get(text.lang_base(lang), 3.5)))


def _line(stage: str, label: str, model: str | None, quantity: float, unit: str, cost: pricing.Cost | None,
          tokens_in: int | None = None, tokens_out: int | None = None) -> dict[str, Any]:
    return {
        "stage": stage, "label": label, "model": model, "quantity": round(quantity, 2), "unit": unit,
        "cost": None if cost is None or cost.value is None else round(cost.value, 6),
        "source": cost.source if cost else "unavailable", "note": cost.note if cost else "",
        "tokens_in": tokens_in, "tokens_out": tokens_out,
    }


def _llm_line(db: Session, stage: str, label: str, model: str | None, tokens_in: int, default_out: int,
              *, units: float | None = None, per_unit_default: int | None = None) -> dict[str, Any]:
    if not model:
        return _line(stage, label, None, 1, "chamada", pricing.Cost(None, "unavailable", "sem modelo de texto"))
    hist = pricing.history_tokens(db, stage, model) or pricing.history_tokens(db, stage)
    if units and per_unit_default:
        per_unit = (hist or {}).get("completion_per_unit") or per_unit_default
        tokens_out = int(units * per_unit)
    else:
        tokens_out = int((hist or {}).get("completion") or default_out)
    cost = pricing.llm_cost(split_ref(model)[1], tokens_in, tokens_out)
    if cost.value is not None and cost.source == "live":
        cost.note = "tokens calibrados pelo histórico" if hist else "tokens estimados pelo tamanho do texto"
        if hist:
            cost.source = "history"
    return _line(stage, label, model, 1, "etapa", cost, tokens_in, tokens_out)


def project_inputs(db: Session, project: Project) -> dict[str, Any]:
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
    scenes = list(project.scenes)
    if scenes:
        n = len(scenes)
        seconds = [s.duration for s in scenes]
        types = {t.value: [s for s in scenes if s.asset_type == t.value] for t in AssetType}
        video_secs = [s.duration for s in types[AssetType.VIDEO.value]]
        narr_chars = sum(len(s.narration) for s in scenes)
    else:
        n = max(1, round(minutes * 60 / (channel.scene_seconds or 7.0)))
        seconds = [minutes * 60 / n] * n
        video_secs = None
        narr_chars = chars
    # sem cenas planejadas, a quantidade depende do nível (duração mínima por cena)
    return {
        "words": words, "chars": chars, "minutes": round(minutes, 2), "scenes": n, "seconds": sum(seconds),
        "avg_scene_seconds": sum(seconds) / n if n else 0, "video_secs": video_secs, "narration_chars": narr_chars,
        "from_target": from_target, "scenes_planned": bool(scenes), "language": channel.language,
    }


def estimate_project(db: Session, project: Project) -> dict[str, Any]:
    inputs = project_inputs(db, project)
    channel = project.channel
    lang = channel.language
    ctx_tokens = _tokens(len(full_context(db, project)), "en")
    script_tokens = _tokens(inputs["chars"], lang)
    tier_cfg = tiers.get_tier_settings(db)
    result: dict[str, Any] = {}
    for tier in Quality:
        t = tier.value
        cfg = tier_cfg[t]
        models = {op: tiers.resolve_model(db, op, t, settings=tier_cfg).model for op in tiers.OPERATIONS}
        lines: list[dict[str, Any]] = []
        if inputs["scenes_planned"]:
            n_scenes, avg_secs = inputs["scenes"], inputs["avg_scene_seconds"]
        else:
            n_scenes = max(1, round(inputs["seconds"] / effective_scene_seconds(channel, cfg)))
            avg_secs = inputs["seconds"] / n_scenes
        text_model = models["text"]
        # 1 roteiro
        lines.append(_llm_line(db, "script", "Análise do roteiro", text_model,
                               ctx_tokens + script_tokens + PROMPT_OVERHEAD, 3200))
        # 2 cenas
        blocks = max(1, math.ceil(inputs["words"] / 650))
        lines.append(_llm_line(db, "scenes", f"Divisão em {n_scenes} cenas ({blocks} blocos)", text_model,
                               blocks * (ctx_tokens + PROMPT_OVERHEAD) + int(script_tokens * 1.15) + 200 * blocks,
                               0, units=n_scenes, per_unit_default=170))
        # 3 visuais
        n = n_scenes
        if inputs["video_secs"] is not None:
            video_secs = inputs["video_secs"]
        else:
            n_video = int(round(n * float(cfg.get("video_share") or 0)))
            video_secs = [avg_secs] * n_video
        img_model = models["image"]
        img_unit = pricing.image_cost(db, split_ref(img_model)[1], cfg.get("image_resolution")) if img_model else None
        img_cost = pricing.Cost(img_unit.value * n, img_unit.source, img_unit.note) if img_unit and img_unit.value is not None else img_unit
        lines.append(_line("visuals", f"Imagens das cenas ({n} × {cfg.get('image_resolution')})", img_model, n,
                           "imagens", img_cost))
        if video_secs:
            vmodel = models["video"]
            vinfo = catalog.video_model(split_ref(vmodel)[1]) if vmodel else None
            res = pricing.video_resolution_for(vinfo, cfg.get("video_resolution") or "720p")
            total_v, src, note, ok = 0.0, "live", "", True
            for secs in video_secs:
                dur = pricing.video_duration_for(vinfo, secs)
                c = pricing.video_cost(db, split_ref(vmodel)[1], res, dur, image_input=True) if vmodel else None
                if c is None or c.value is None:
                    ok, note = False, (c.note if c else "sem modelo de vídeo")
                    break
                total_v += c.value
                src, note = c.source, c.note
            lines.append(_line("visuals", f"Vídeos IA ({len(video_secs)} cenas, {res})", vmodel, len(video_secs),
                               "clipes", pricing.Cost(total_v if ok else None, src if ok else "unavailable", note)))
        motion_n = n - len(video_secs)
        lines.append(_line("visuals", f"Movimento local ({motion_n} cenas)", "ffmpeg (local)", motion_n, "clipes",
                           pricing.Cost(0.0, "free", "renderizado no servidor")))
        # 4 narração
        try:
            tts = tts_settings(db, channel, t)
            tts_model = tts["model"]
        except Exception:  # noqa: BLE001 - sem modelo de TTS disponível
            tts_model = None
        tts_cost = pricing.tts_cost(db, split_ref(tts_model)[1], inputs["narration_chars"], inputs["seconds"]) if tts_model else None
        lines.append(_line("narration", f"Narração ({inputs['narration_chars']:,} caracteres)".replace(",", "."),
                           tts_model, inputs["narration_chars"], "caracteres", tts_cost))
        # 5 thumbnail
        concepts = int(cfg.get("thumb_concepts") or 3)
        variations = int(cfg.get("thumb_variations") or 1)
        lines.append(_llm_line(db, "thumbnail", f"Conceitos de thumbnail ({concepts})", text_model,
                               ctx_tokens + PROMPT_OVERHEAD + 900, 0, units=concepts, per_unit_default=380))
        th_model = models["thumbnail"]
        th_unit = pricing.image_cost(db, split_ref(th_model)[1], cfg.get("image_resolution")) if th_model else None
        imgs = concepts * variations
        th_cost = pricing.Cost(th_unit.value * imgs, th_unit.source, th_unit.note) if th_unit and th_unit.value is not None else th_unit
        lines.append(_line("thumbnail", f"Imagens de thumbnail ({concepts} × {variations})", th_model, imgs, "imagens", th_cost))
        # 6 metadados
        lines.append(_llm_line(db, "metadata", "Título, descrição e tags", text_model,
                               ctx_tokens + script_tokens + PROMPT_OVERHEAD + n * 22, 2600))
        # 7 aprendizado
        if channel.auto_learn:
            lines.append(_llm_line(db, "learning", "Aprendizados para a Skill", text_model,
                                   ctx_tokens + PROMPT_OVERHEAD + 1500, 900))
        priced = [ln for ln in lines if ln["cost"] is not None]
        total = sum(ln["cost"] for ln in priced)
        result[t] = {
            "scenes": n_scenes,
            "total": round(total, 4),
            "complete": len(priced) == len(lines),
            "missing": [ln["label"] for ln in lines if ln["cost"] is None],
            "lines": lines,
            "models": models,
        }
    return {"inputs": inputs, "tiers": result, "current": project.quality,
            "catalog_at": str(catalog.fetched_at(catalog.KINDS["text"]) or "")}
