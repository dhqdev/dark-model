"""Registro de providers. Referências de modelo podem ter prefixo de provider ("local:...")."""

from __future__ import annotations

import threading

import httpx

from .. import catalog
from ..config import get_settings
from .base import ProviderError
from .local import LocalMotion
from .openrouter import OpenRouterClient, OpenRouterImage, OpenRouterLLM, OpenRouterTTS, OpenRouterVideo

_lock = threading.Lock()
_client: OpenRouterClient | None = None
_client_key: tuple | None = None
_transport: httpx.BaseTransport | None = None
_video_poll_seconds: float | None = None
_sleep = None


def configure_for_tests(transport: httpx.BaseTransport | None, *, video_poll_seconds: float | None = 0.0,
                        sleep=lambda _s: None) -> None:
    """Injeta um transporte HTTP falso (testes e modo de demonstração)."""
    global _transport, _video_poll_seconds, _sleep
    _transport = transport
    _video_poll_seconds = video_poll_seconds
    _sleep = sleep
    reset()


def reset() -> None:
    global _client, _client_key
    with _lock:
        if _client is not None:
            _client.close()
        _client = None
        _client_key = None
    catalog.clear_memory()


def openrouter_client() -> OpenRouterClient:
    global _client, _client_key
    s = get_settings()
    key = (s.openrouter_api_key, s.openrouter_base_url, s.openrouter_management_key, s.app_public_url, id(_transport))
    with _lock:
        if _client is None or _client_key != key:
            if _client is not None:
                _client.close()
            kwargs = {}
            if _sleep is not None:
                kwargs["sleep"] = _sleep
            _client = OpenRouterClient(
                s.openrouter_api_key,
                s.openrouter_base_url,
                app_url=s.app_public_url,
                app_title=s.app_name,
                management_key=s.openrouter_management_key,
                transport=_transport,
                **kwargs,
            )
            _client_key = key
        return _client


def split_ref(ref: str) -> tuple[str, str]:
    """'openrouter:google/x' → ('openrouter', 'google/x'); sem prefixo = openrouter."""
    if ":" in ref.split("/")[0]:
        provider, _, model = ref.partition(":")
        return provider, model
    return "openrouter", ref


def llm(provider: str = "openrouter") -> OpenRouterLLM:
    if provider != "openrouter":
        raise ProviderError(f"provider de texto desconhecido: {provider}")
    return OpenRouterLLM(openrouter_client(), catalog.model_info)


def image(provider: str = "openrouter") -> OpenRouterImage:
    if provider != "openrouter":
        raise ProviderError(f"provider de imagem desconhecido: {provider}")
    return OpenRouterImage(openrouter_client(), catalog.image_caps, catalog.is_chat_image_model)


def tts(provider: str = "openrouter") -> OpenRouterTTS:
    if provider != "openrouter":
        raise ProviderError(f"provider de narração desconhecido: {provider}")
    return OpenRouterTTS(openrouter_client())


def video(provider: str = "openrouter") -> OpenRouterVideo:
    if provider != "openrouter":
        raise ProviderError(f"provider de vídeo desconhecido: {provider}")
    kwargs = {}
    if _video_poll_seconds is not None:
        kwargs["poll_seconds"] = _video_poll_seconds
    return OpenRouterVideo(openrouter_client(), catalog.video_model, **kwargs)


def motion() -> LocalMotion:
    return LocalMotion()
