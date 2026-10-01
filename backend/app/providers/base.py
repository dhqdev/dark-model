"""Contratos dos providers. Trocar de fornecedor = implementar estas interfaces e registrar."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderError(Exception):
    """Falha ao chamar um provider. `retryable` indica se tentar de novo pode resolver."""

    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False, code: str = ""):
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.code = code


class CanceledError(Exception):
    """O usuário cancelou a tarefa enquanto ela rodava."""


@dataclass
class Usage:
    provider: str
    model: str
    operation: str  # llm | image | tts | video | motion
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    units: float = 0.0
    unit: str = ""
    cost_usd: float | None = None
    # reported | generation | pending | free | unknown
    cost_source: str = "unknown"
    generation_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResult:
    text: str
    model: str
    usage: Usage
    finish_reason: str = ""
    data: Any = None


@dataclass
class MediaResult:
    data: bytes
    mime: str
    usage: Usage
    meta: dict[str, Any] = field(default_factory=dict)


ProgressFn = Callable[[float, str], None]
CancelFn = Callable[[], bool]


class LLMProvider(Protocol):
    name: str

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        json_schema: dict[str, Any] | None = None,
        schema_name: str = "result",
        temperature: float | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
        session_id: str | None = None,
    ) -> LLMResult: ...


class ImageProvider(Protocol):
    name: str

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        aspect_ratio: str = "16:9",
        resolution: str | None = None,
        quality: str | None = None,
        seed: int | None = None,
        session_id: str | None = None,
    ) -> MediaResult: ...


class TTSProvider(Protocol):
    name: str

    def synthesize(
        self,
        *,
        model: str,
        text: str,
        voice: str | None,
        speed: float | None = None,
        style: str | None = None,
        session_id: str | None = None,
    ) -> MediaResult: ...


class VideoProvider(Protocol):
    name: str

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        duration: int,
        resolution: str | None,
        aspect_ratio: str = "16:9",
        first_frame: bytes | None = None,
        progress: ProgressFn | None = None,
        canceled: CancelFn | None = None,
        session_id: str | None = None,
    ) -> MediaResult: ...
