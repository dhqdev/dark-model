"""Catálogo de modelos da OpenRouter com preços reais, em cache no banco.

O cache é compartilhado entre API e worker e renovado a cada CATALOG_TTL_MINUTES.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .config import get_settings
from .db import session_scope
from .models import CatalogEntry, utcnow
from .providers.base import ProviderError

log = logging.getLogger(__name__)

# chave do cache → como buscar
KINDS = {
    "text": "models:text",
    "image_chat": "models:image",
    "speech": "models:speech",
    "image": "images:models",
    "video": "videos:models",
}

_mem: dict[str, tuple[float, Any]] = {}
_mem_lock = threading.Lock()
_MEM_TTL = 60.0


def _client():
    from .providers.registry import openrouter_client

    return openrouter_client()


def _fetch(key: str) -> Any:
    client = _client()
    if key == KINDS["text"]:
        return client.list_models("text")
    if key == KINDS["image_chat"]:
        return client.list_models("image")
    if key == KINDS["speech"]:
        return client.list_models("speech")
    if key == KINDS["image"]:
        return client.list_image_models()
    if key == KINDS["video"]:
        return client.list_video_models()
    if key.startswith("images:endpoints:"):
        return client.image_model_endpoints(key.split(":", 2)[2])
    raise KeyError(key)


def _load(key: str) -> tuple[Any, Any] | None:
    with session_scope() as db:
        row = db.get(CatalogEntry, key)
        if row is None:
            return None
        return row.data, row.fetched_at


def _store(key: str, data: Any) -> None:
    for attempt in range(2):
        try:
            with session_scope() as db:
                row = db.get(CatalogEntry, key)
                if row is None:
                    db.add(CatalogEntry(key=key, data=data, fetched_at=utcnow()))
                else:
                    row.data = data
                    row.fetched_at = utcnow()
            break
        except IntegrityError:
            # API e worker buscaram o catálogo ao mesmo tempo: o outro já gravou; atualiza
            if attempt:
                raise
    with _mem_lock:
        _mem[key] = (time.monotonic(), data)


def get(key: str, *, refresh_if_stale: bool = True, force: bool = False) -> Any:
    """Dados do catálogo (lista). Busca na OpenRouter quando ausente ou vencido."""
    if not force:
        with _mem_lock:
            hit = _mem.get(key)
        if hit and time.monotonic() - hit[0] < _MEM_TTL:
            return hit[1]
    stored = None if force else _load(key)
    ttl = timedelta(minutes=get_settings().catalog_ttl_minutes)
    if stored is not None:
        data, fetched_at = stored
        fresh = utcnow() - fetched_at < ttl
        if fresh or not refresh_if_stale:
            with _mem_lock:
                _mem[key] = (time.monotonic(), data)
            return data
    if not get_settings().openrouter_configured:
        return stored[0] if stored else []
    try:
        data = _fetch(key)
    except ProviderError as exc:
        log.warning("catálogo %s indisponível: %s", key, exc)
        if stored is not None:
            return stored[0]
        raise
    _store(key, data)
    return data


def fetched_at(key: str):
    stored = _load(key)
    return stored[1] if stored else None


def refresh_all() -> dict[str, Any]:
    report: dict[str, Any] = {}
    for kind, key in KINDS.items():
        try:
            data = get(key, force=True)
            report[kind] = {"ok": True, "count": len(data or [])}
        except ProviderError as exc:
            report[kind] = {"ok": False, "error": str(exc)}
    with session_scope() as db:
        for row in db.scalars(select(CatalogEntry).where(CatalogEntry.key.like("images:endpoints:%"))):
            db.delete(row)
    with _mem_lock:
        for k in [k for k in _mem if k.startswith("images:endpoints:")]:
            _mem.pop(k, None)
    return report


def clear_memory() -> None:
    with _mem_lock:
        _mem.clear()


# ------------------------------------------------------------------ consultas


def _find(items: list[dict[str, Any]] | None, model_id: str) -> dict[str, Any] | None:
    for item in items or []:
        if item.get("id") == model_id or item.get("canonical_slug") == model_id:
            return item
    return None


def safe_get(key: str) -> list[dict[str, Any]]:
    try:
        return list(get(key) or [])
    except ProviderError:
        return []


def model_info(model_id: str) -> dict[str, Any] | None:
    """Modelo do /models (texto, TTS ou imagem via chat)."""
    for key in (KINDS["text"], KINDS["speech"], KINDS["image_chat"]):
        found = _find(safe_get(key), model_id)
        if found:
            return found
    return None


def image_caps(model_id: str) -> dict[str, Any] | None:
    """Parâmetros aceitos pelo modelo na API de imagens (None = não está na API /images)."""
    found = _find(safe_get(KINDS["image"]), model_id)
    if found is None:
        return None
    return dict(found.get("supported_parameters") or {})


def is_chat_image_model(model_id: str) -> bool:
    return _find(safe_get(KINDS["image_chat"]), model_id) is not None


def image_endpoints(model_id: str) -> list[dict[str, Any]]:
    try:
        return list(get(f"images:endpoints:{model_id}") or [])
    except ProviderError:
        return []


def prefetch_image_endpoints(model_ids: list[str], workers: int = 8) -> None:
    """Busca em paralelo os preços (endpoints) dos modelos de imagem que ainda não estão em cache."""
    from concurrent.futures import ThreadPoolExecutor

    api_ids = {m.get("id") for m in safe_get(KINDS["image"])}
    missing = [m for m in model_ids if m in api_ids and _load(f"images:endpoints:{m}") is None]
    if not missing or not get_settings().openrouter_configured:
        return
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(image_endpoints, missing))


def video_model(model_id: str) -> dict[str, Any] | None:
    return _find(safe_get(KINDS["video"]), model_id)


def speech_voices(model_id: str) -> list[str]:
    info = _find(safe_get(KINDS["speech"]), model_id)
    return list((info or {}).get("supported_voices") or [])


def exists(kind: str, model_id: str) -> bool:
    if kind == "image":
        return _find(safe_get(KINDS["image"]), model_id) is not None or is_chat_image_model(model_id)
    return _find(safe_get(KINDS[kind]), model_id) is not None
