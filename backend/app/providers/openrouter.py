"""Cliente da OpenRouter e providers de LLM, imagem, TTS e vídeo.

Endpoints usados (https://openrouter.ai/api/v1):
  POST /chat/completions            texto (JSON estruturado)        → usage.cost na resposta
  POST /images                      imagem                          → usage.cost na resposta
  POST /audio/speech                narração (bytes de áudio)       → custo via X-Generation-Id + /generation
  POST /videos, GET /videos/{id}    vídeo assíncrono (polling)      → usage.cost ao concluir
  GET  /models, /images/models, /videos/models                     → catálogo com preços reais
  GET  /generation?id=  /key  /credits                             → custo de uma geração e saldo
"""

from __future__ import annotations

import base64
import logging
import random
import time
from collections.abc import Callable
from typing import Any

import httpx

from .. import media
from .base import CanceledError, LLMResult, MediaResult, ProgressFn, CancelFn, ProviderError, Usage

log = logging.getLogger(__name__)

PROVIDER = "openrouter"
# Repetir automaticamente apenas quando a requisição certamente não foi processada/cobrada.
_AUTO_RETRY_STATUS = {429, 500, 502, 503, 504, 529}


def _error_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:300] or resp.reason_phrase
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        msg = str(err.get("message") or "")
        meta = err.get("metadata") or {}
        raw = meta.get("raw") if isinstance(meta, dict) else None
        if raw and isinstance(raw, str) and raw not in msg:
            msg = f"{msg} — {raw[:300]}"
        return msg or str(err)
    if isinstance(err, str):
        return err
    return str(body)[:300]


def error_from_response(resp: httpx.Response) -> ProviderError:
    status = resp.status_code
    msg = _error_message(resp)
    if status == 401:
        return ProviderError(f"Chave da OpenRouter inválida ou ausente ({msg})", status=status, code="auth")
    if status == 402:
        return ProviderError(f"Saldo insuficiente na OpenRouter ({msg})", status=status, code="credits")
    if status == 403:
        return ProviderError(f"Pedido bloqueado pela moderação/política do modelo ({msg})", status=status, code="moderation")
    if status == 404:
        return ProviderError(f"Modelo ou recurso não encontrado na OpenRouter ({msg})", status=status, code="not_found")
    if status in (408, 425, 429) or status >= 500:
        return ProviderError(f"OpenRouter indisponível no momento [{status}] ({msg})", status=status, retryable=True)
    return ProviderError(f"OpenRouter recusou o pedido [{status}] ({msg})", status=status)


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        *,
        app_url: str = "",
        app_title: str = "Dark Model",
        management_key: str = "",
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.api_key = api_key
        self.management_key = management_key
        self.base_url = base_url.rstrip("/")
        self._sleep = sleep
        headers = {"X-OpenRouter-Title": app_title, "X-Title": app_title}
        if app_url:
            headers["HTTP-Referer"] = app_url
        self._http = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            transport=transport,
            timeout=httpx.Timeout(connect=20.0, read=300.0, write=120.0, pool=60.0),
            follow_redirects=True,
        )

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------ HTTP base

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
        retries: int = 3,
        management: bool = False,
    ) -> httpx.Response:
        key = self.management_key if management and self.management_key else self.api_key
        if not key:
            raise ProviderError("OPENROUTER_API_KEY não configurada no servidor", code="auth")
        headers = {"Authorization": f"Bearer {key}"}
        attempt = 0
        while True:
            retry_after: float | None = None
            try:
                resp = self._http.request(
                    method, path, json=json, params=params, headers=headers,
                    timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
                )
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
                err = ProviderError(f"Sem conexão com a OpenRouter: {exc}", retryable=True, code="network")
                auto = True
            except httpx.TimeoutException as exc:
                # a geração pode ter acontecido; não repete aqui para não cobrar duas vezes
                raise ProviderError(f"Tempo esgotado aguardando a OpenRouter ({path})", retryable=True, code="timeout") from exc
            except httpx.TransportError as exc:
                raise ProviderError(f"Falha de rede com a OpenRouter: {exc}", retryable=True, code="network") from exc
            else:
                if resp.status_code < 400:
                    return resp
                err = error_from_response(resp)
                auto = resp.status_code in _AUTO_RETRY_STATUS
                ra = resp.headers.get("retry-after")
                if ra:
                    try:
                        retry_after = float(ra)
                    except ValueError:
                        retry_after = None
            attempt += 1
            if not auto or attempt > retries:
                raise err
            delay = retry_after if retry_after is not None else min(30.0, 1.5 * 2 ** (attempt - 1))
            self._sleep(delay + random.uniform(0, 0.5))

    def get_json(self, path: str, **kw: Any) -> Any:
        return self.request("GET", path, **kw).json()

    def post_json(self, path: str, payload: dict[str, Any], **kw: Any) -> Any:
        resp = self.request("POST", path, json=payload, **kw)
        data = resp.json()
        if isinstance(data, dict) and data.get("error") and not data.get("choices") and not data.get("data"):
            err = data["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            code = err.get("code") if isinstance(err, dict) else None
            raise ProviderError(f"OpenRouter: {msg}", status=code if isinstance(code, int) else None,
                                retryable=isinstance(code, int) and code >= 500)
        return data

    # ------------------------------------------------------------------ catálogo / conta

    def list_models(self, output_modalities: str | None = None) -> list[dict[str, Any]]:
        params = {"output_modalities": output_modalities} if output_modalities else None
        return list(self.get_json("/models", params=params).get("data") or [])

    def list_image_models(self) -> list[dict[str, Any]]:
        return list(self.get_json("/images/models").get("data") or [])

    def image_model_endpoints(self, model_id: str) -> list[dict[str, Any]]:
        author, _, slug = model_id.partition("/")
        return list(self.get_json(f"/images/models/{author}/{slug}/endpoints").get("endpoints") or [])

    def list_video_models(self) -> list[dict[str, Any]]:
        return list(self.get_json("/videos/models").get("data") or [])

    def key_info(self) -> dict[str, Any]:
        return dict(self.get_json("/key", retries=1).get("data") or {})

    def credits(self) -> dict[str, Any]:
        return dict(self.get_json("/credits", retries=1, management=True).get("data") or {})

    def generation(self, generation_id: str) -> dict[str, Any] | None:
        try:
            data = self.get_json("/generation", params={"id": generation_id}, retries=1)
        except ProviderError as exc:
            if exc.status == 404:
                return None
            raise
        return dict(data.get("data") or {}) or None

    def generation_cost(self, generation_id: str, waits: tuple[float, ...] = (0.5, 1.5, 3.0)) -> float | None:
        """Custo real de uma geração. A OpenRouter leva alguns segundos para registrar."""
        for wait in (0.0, *waits):
            if wait:
                self._sleep(wait)
            try:
                info = self.generation(generation_id)
            except ProviderError:
                info = None
            if info and info.get("total_cost") is not None:
                return float(info["total_cost"])
        return None


def _usage_cost(usage: dict[str, Any]) -> tuple[float | None, str]:
    cost = usage.get("cost") if usage else None
    if cost is None:
        return None, "pending"
    return float(cost), "reported"


def _sniff_image_mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def _decode_data_url(url: str) -> tuple[bytes, str]:
    if url.startswith("data:"):
        header, _, b64 = url.partition(",")
        mime = header[5:].split(";")[0] or "image/png"
        return base64.b64decode(b64), mime
    raise ProviderError("imagem retornada como URL externa não suportada")


# ---------------------------------------------------------------------- providers

CatalogLookup = Callable[[str], dict[str, Any] | None]


class OpenRouterLLM:
    name = PROVIDER

    def __init__(self, client: OpenRouterClient, model_info: CatalogLookup):
        self.client = client
        self.model_info = model_info

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
    ) -> LLMResult:
        info = self.model_info(model) or {}
        params = set(info.get("supported_parameters") or [])
        payload: dict[str, Any] = {"model": model, "messages": messages}
        if temperature is not None and (not params or "temperature" in params):
            payload["temperature"] = temperature
        if max_tokens:
            limit = (info.get("top_provider") or {}).get("max_completion_tokens")
            payload["max_tokens"] = min(max_tokens, int(limit)) if limit else max_tokens
        if json_schema is not None:
            if "structured_outputs" in params:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "strict": True, "schema": json_schema},
                }
            elif not params or "response_format" in params:
                payload["response_format"] = {"type": "json_object"}
        if reasoning_effort and "reasoning" in params:
            payload["reasoning"] = {"effort": reasoning_effort}
        if session_id:
            payload["session_id"] = session_id[:256]
        try:
            data = self.client.post_json("/chat/completions", payload, timeout=600)
        except ProviderError as exc:
            fmt = payload.get("response_format", {}).get("type")
            if exc.status == 400 and fmt == "json_schema":
                # alguns provedores rejeitam o schema estrito: tenta modo JSON simples
                payload["response_format"] = {"type": "json_object"}
                data = self.client.post_json("/chat/completions", payload, timeout=600)
            else:
                raise
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError("A OpenRouter não retornou resposta do modelo", retryable=True)
        choice = choices[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        usage = data.get("usage") or {}
        cost, source = _usage_cost(usage)
        details = usage.get("completion_tokens_details") or {}
        u = Usage(
            provider=PROVIDER,
            model=data.get("model") or model,
            operation="llm",
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            reasoning_tokens=int(details.get("reasoning_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
            cost_usd=cost,
            cost_source=source if data.get("id") or cost is not None else "unknown",
            generation_id=data.get("id"),
        )
        return LLMResult(text=str(content), model=u.model, usage=u, finish_reason=str(choice.get("finish_reason") or ""))


class OpenRouterImage:
    name = PROVIDER

    def __init__(
        self,
        client: OpenRouterClient,
        image_caps: CatalogLookup,
        chat_image_model: Callable[[str], bool],
    ):
        self.client = client
        self.image_caps = image_caps
        self.chat_image_model = chat_image_model

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
    ) -> MediaResult:
        caps = self.image_caps(model)
        if caps is None and self.chat_image_model(model):
            return self._via_chat(model=model, prompt=prompt, aspect_ratio=aspect_ratio, session_id=session_id)

        def allowed(param: str, value: Any = None) -> bool:
            if caps is None:
                return param == "aspect_ratio"
            desc = caps.get(param)
            if not desc:
                return False
            if isinstance(desc, dict) and desc.get("type") == "enum" and value is not None:
                return value in (desc.get("values") or [])
            return True

        payload: dict[str, Any] = {"model": model, "prompt": prompt}
        if allowed("n"):
            payload["n"] = 1
        if aspect_ratio and allowed("aspect_ratio", aspect_ratio):
            payload["aspect_ratio"] = aspect_ratio
        if resolution and allowed("resolution", resolution):
            payload["resolution"] = resolution
        if quality and allowed("quality", quality):
            payload["quality"] = quality
        if allowed("output_format", "png"):
            payload["output_format"] = "png"
        if seed is not None and allowed("seed"):
            payload["seed"] = seed
        if session_id:
            payload["session_id"] = session_id[:256]
        resp = self.client.request("POST", "/images", json=payload, timeout=600)
        data = resp.json()
        items = data.get("data") or []
        if not items or not items[0].get("b64_json"):
            raise ProviderError("O modelo não retornou nenhuma imagem (possível bloqueio de conteúdo)", retryable=True)
        raw = base64.b64decode(items[0]["b64_json"])
        mime = items[0].get("media_type") or _sniff_image_mime(raw)
        usage = data.get("usage") or {}
        cost, source = _usage_cost(usage)
        gen_id = resp.headers.get("x-generation-id") or data.get("id")
        u = Usage(
            provider=PROVIDER, model=model, operation="image",
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
            units=1, unit="images", cost_usd=cost,
            cost_source=source if (gen_id or cost is not None) else "unknown",
            generation_id=gen_id,
        )
        return MediaResult(data=raw, mime=mime, usage=u, meta={"params": {k: v for k, v in payload.items() if k != "prompt"}})

    def _via_chat(self, *, model: str, prompt: str, aspect_ratio: str, session_id: str | None) -> MediaResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "modalities": ["image", "text"],
            "image_config": {"aspect_ratio": aspect_ratio},
        }
        if session_id:
            payload["session_id"] = session_id[:256]
        data = self.client.post_json("/chat/completions", payload, timeout=600)
        message = ((data.get("choices") or [{}])[0]).get("message") or {}
        images = message.get("images") or []
        if not images:
            raise ProviderError("O modelo não retornou nenhuma imagem (possível bloqueio de conteúdo)", retryable=True)
        raw, mime = _decode_data_url(images[0]["image_url"]["url"])
        usage = data.get("usage") or {}
        cost, source = _usage_cost(usage)
        u = Usage(
            provider=PROVIDER, model=model, operation="image",
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
            units=1, unit="images", cost_usd=cost, cost_source=source, generation_id=data.get("id"),
        )
        return MediaResult(data=raw, mime=mime, usage=u, meta={"params": {"via": "chat", "aspect_ratio": aspect_ratio}})


class OpenRouterTTS:
    name = PROVIDER
    # limite seguro por requisição (OpenAI aceita 4096 caracteres)
    max_chars = 3500

    def __init__(self, client: OpenRouterClient):
        self.client = client

    def synthesize(
        self,
        *,
        model: str,
        text: str,
        voice: str | None,
        speed: float | None = None,
        style: str | None = None,
        session_id: str | None = None,
    ) -> MediaResult:
        payload: dict[str, Any] = {"model": model, "input": text, "response_format": "mp3"}
        if voice:
            payload["voice"] = voice
        if speed and abs(speed - 1.0) > 1e-3:
            payload["speed"] = round(float(speed), 2)
        if style and model.startswith("openai/"):
            payload["provider"] = {"options": {"openai": {"instructions": style}}}
        if session_id:
            payload["session_id"] = session_id[:256]
        resp = self.client.request("POST", "/audio/speech", json=payload, timeout=600)
        ctype = resp.headers.get("content-type", "")
        if "json" in ctype:
            raise ProviderError(f"TTS retornou erro: {_error_message(resp)}", retryable=True)
        if not resp.content:
            raise ProviderError("TTS retornou áudio vazio", retryable=True)
        audio = media.to_mp3(resp.content, ctype or "audio/mpeg")
        gen_id = resp.headers.get("x-generation-id")
        cost = self.client.generation_cost(gen_id) if gen_id else None
        u = Usage(
            provider=PROVIDER, model=model, operation="tts", units=len(text), unit="chars",
            cost_usd=cost,
            cost_source="generation" if cost is not None else ("pending" if gen_id else "unknown"),
            generation_id=gen_id,
        )
        return MediaResult(data=audio, mime="audio/mpeg", usage=u, meta={"voice": voice, "speed": speed})


class OpenRouterVideo:
    name = PROVIDER

    def __init__(self, client: OpenRouterClient, video_info: CatalogLookup, poll_seconds: float = 6.0,
                 max_wait_seconds: float = 1800.0):
        self.client = client
        self.video_info = video_info
        self.poll_seconds = poll_seconds
        self.max_wait_seconds = max_wait_seconds

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
    ) -> MediaResult:
        info = self.video_info(model) or {}
        payload: dict[str, Any] = {"model": model, "prompt": prompt, "duration": int(duration)}
        ratios = info.get("supported_aspect_ratios")
        if not ratios or aspect_ratio in ratios:
            payload["aspect_ratio"] = aspect_ratio
        resolutions = info.get("supported_resolutions")
        if resolution and (not resolutions or resolution in resolutions):
            payload["resolution"] = resolution
        if info.get("generate_audio") is not None:
            payload["generate_audio"] = False
        if first_frame and "first_frame" in (info.get("supported_frame_images") or []):
            payload["frame_images"] = [{
                "type": "image_url",
                "image_url": {"url": media.jpeg_data_url(first_frame)},
                "frame_type": "first_frame",
            }]
        if session_id:
            payload["session_id"] = session_id[:256]
        job = self.client.post_json("/videos", payload, timeout=120)
        job_id = job.get("id")
        if not job_id:
            raise ProviderError("A OpenRouter não retornou o id do vídeo", retryable=True)
        started = time.monotonic()
        status = job
        while True:
            state = str(status.get("status") or "")
            if state == "completed":
                break
            if state in {"failed", "cancelled", "expired"}:
                raise ProviderError(
                    f"Geração de vídeo {state}: {status.get('error') or 'sem detalhes'}",
                    retryable=state == "expired",
                )
            if canceled and canceled():
                raise CanceledError("vídeo cancelado (a OpenRouter pode cobrar o que já foi processado)")
            elapsed = time.monotonic() - started
            if elapsed > self.max_wait_seconds:
                raise ProviderError("Vídeo não ficou pronto a tempo", retryable=True, code="timeout")
            if progress:
                progress(min(0.9, 0.1 + elapsed / 240.0), f"vídeo {state or 'na fila'} · {int(elapsed)}s")
            if self.poll_seconds:
                self.client._sleep(self.poll_seconds)
            status = self.client.get_json(f"/videos/{job_id}", timeout=60)
        if progress:
            progress(0.92, "baixando vídeo")
        resp = self.client.request("GET", f"/videos/{job_id}/content", params={"index": 0}, timeout=900)
        usage = status.get("usage") or {}
        cost = usage.get("cost")
        gen_id = status.get("generation_id")
        u = Usage(
            provider=PROVIDER, model=model, operation="video", units=float(duration), unit="seconds",
            cost_usd=float(cost) if cost is not None else None,
            cost_source="reported" if cost is not None else ("pending" if gen_id else "unknown"),
            generation_id=gen_id, meta={"video_job_id": job_id},
        )
        return MediaResult(
            data=resp.content, mime=resp.headers.get("content-type", "video/mp4").split(";")[0] or "video/mp4",
            usage=u, meta={"params": {k: v for k, v in payload.items() if k not in {"prompt", "frame_images"}},
                           "first_frame": bool(payload.get("frame_images"))},
        )
