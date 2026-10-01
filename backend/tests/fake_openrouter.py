"""Simulador da API da OpenRouter para testes e demonstração local.

Reproduz os formatos de resposta documentados no SDK oficial (openrouter 1.3.x):
/models, /images, /images/models, /audio/speech, /videos, /generation, /key, /credits e
/chat/completions com JSON estruturado. Também pode rodar como servidor:

    python -m tests.fake_openrouter --port 9911
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw

NOW = 1_760_000_000

TEXT_MODELS = [
    {"id": "google/gemini-2.5-flash", "name": "Google: Gemini 2.5 Flash", "created": NOW - 9_000_000,
     "pricing": {"prompt": "0.0000003", "completion": "0.0000025"}, "context_length": 1_048_576},
    {"id": "google/gemini-3-flash-preview", "name": "Google: Gemini 3 Flash Preview", "created": NOW - 1_000_000,
     "pricing": {"prompt": "0.0000005", "completion": "0.000003"}, "context_length": 1_048_576},
    {"id": "anthropic/claude-sonnet-4.5", "name": "Anthropic: Claude Sonnet 4.5", "created": NOW - 4_000_000,
     "pricing": {"prompt": "0.000003", "completion": "0.000015"}, "context_length": 1_000_000},
    {"id": "anthropic/claude-opus-4.5", "name": "Anthropic: Claude Opus 4.5", "created": NOW - 2_000_000,
     "pricing": {"prompt": "0.000005", "completion": "0.000025"}, "context_length": 200_000},
    {"id": "openai/gpt-5", "name": "OpenAI: GPT-5", "created": NOW - 6_000_000,
     "pricing": {"prompt": "0.00000125", "completion": "0.00001"}, "context_length": 400_000},
    {"id": "meta-llama/llama-3.3-70b-instruct:free", "name": "free variant", "created": NOW,
     "pricing": {"prompt": "0", "completion": "0"}, "context_length": 128_000},
]
for _m in TEXT_MODELS:
    _m.update({
        "canonical_slug": _m["id"], "architecture": {"input_modalities": ["text"], "output_modalities": ["text"],
                                                       "modality": "text->text"},
        "supported_parameters": ["max_tokens", "temperature", "response_format", "structured_outputs", "reasoning"],
        "top_provider": {"max_completion_tokens": 64_000, "context_length": _m["context_length"]},
        "supported_voices": None,
    })

CHAT_IMAGE_MODELS = [
    {"id": "openai/gpt-5-image-mini", "name": "OpenAI: GPT-5 Image Mini (chat only)", "created": NOW - 3_000_000,
     "pricing": {"prompt": "0.0000025", "completion": "0.000008"},
     "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["image", "text"]},
     "supported_parameters": ["max_tokens"], "context_length": 400_000},
    {"id": "google/gemini-2.5-flash-image", "name": "Google: Nano Banana", "created": NOW - 5_000_000,
     "pricing": {"prompt": "0.0000003", "completion": "0.0000025", "image_output": "0.00003"},
     "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["image", "text"]},
     "supported_parameters": ["max_tokens", "temperature"], "context_length": 32_768},
]

IMAGE_MODELS = [
    {"id": "google/gemini-2.5-flash-image", "name": "Google: Nano Banana", "created": NOW - 5_000_000,
     "description": "fast image model", "endpoints": "/api/v1/images/models/google/gemini-2.5-flash-image/endpoints",
     "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["image"]},
     "supported_parameters": {"aspect_ratio": {"type": "enum", "values": ["1:1", "16:9", "9:16", "4:3"]},
                              "n": {"type": "range", "min": 1, "max": 4},
                              "output_format": {"type": "enum", "values": ["png", "jpeg"]}},
     "supports_streaming": False},
    {"id": "google/gemini-3-pro-image-preview", "name": "Google: Nano Banana Pro", "created": NOW - 1_500_000,
     "description": "pro image model", "endpoints": "/api/v1/images/models/google/gemini-3-pro-image-preview/endpoints",
     "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["image"]},
     "supported_parameters": {"aspect_ratio": {"type": "enum", "values": ["1:1", "16:9", "9:16"]},
                              "resolution": {"type": "enum", "values": ["1K", "2K", "4K"]},
                              "output_format": {"type": "enum", "values": ["png", "jpeg"]}},
     "supports_streaming": False},
]
IMAGE_PRICING = {
    "google/gemini-2.5-flash-image": [{"billable": "output_image", "cost_usd": 0.039, "unit": "image"}],
    "google/gemini-3-pro-image-preview": [
        {"billable": "output_image", "cost_usd": 0.134, "unit": "image", "variant": "1K"},
        {"billable": "output_image", "cost_usd": 0.134, "unit": "image", "variant": "2K"},
        {"billable": "output_image", "cost_usd": 0.24, "unit": "image", "variant": "4K"},
    ],
}

SPEECH_MODELS = [
    {"id": "openai/gpt-4o-mini-tts", "name": "OpenAI: GPT-4o mini TTS", "created": NOW - 7_000_000,
     "pricing": {"prompt": "0.0000006", "completion": "0.000012"},
     "supported_voices": ["alloy", "ash", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer"]},
    {"id": "mistralai/voxtral-mini-tts-2603", "name": "Mistral: Voxtral Mini TTS", "created": NOW - 800_000,
     "pricing": {"prompt": "0.000016", "completion": "0"}, "supported_voices": ["amelia", "oliver", "jakub", "zofia"]},
    {"id": "google/gemini-3.1-flash-tts-preview", "name": "Google: Gemini 3.1 Flash TTS", "created": NOW - 600_000,
     "pricing": {"prompt": "0.000001", "completion": "0.00002"}, "supported_voices": ["Kore", "Puck", "Charon"]},
]
for _m in SPEECH_MODELS:
    _m.update({"canonical_slug": _m["id"], "architecture": {"input_modalities": ["text"], "output_modalities": ["speech"]},
               "supported_parameters": ["voice", "speed", "response_format"], "context_length": 4096})

VIDEO_MODELS = [
    {"id": "google/veo-3.1", "name": "Google: Veo 3.1", "canonical_slug": "google/veo-3.1", "created": NOW - 2_500_000,
     "supported_durations": [4, 6, 8], "supported_resolutions": ["720p", "1080p"],
     "supported_aspect_ratios": ["16:9", "9:16"], "supported_frame_images": ["first_frame", "last_frame"],
     "generate_audio": True, "seed": True, "creativity": None, "upscale_factor": None, "supported_sizes": None,
     "allowed_passthrough_parameters": [],
     "pricing_skus": {"duration_seconds_with_audio": "0.40", "duration_seconds_without_audio": "0.20"}},
    {"id": "alibaba/wan-2.6", "name": "Alibaba: Wan 2.6", "canonical_slug": "alibaba/wan-2.6", "created": NOW - 1_200_000,
     "supported_durations": [5, 10], "supported_resolutions": ["480p", "720p", "1080p"],
     "supported_aspect_ratios": ["16:9", "9:16", "1:1"], "supported_frame_images": ["first_frame"],
     "generate_audio": None, "seed": True, "creativity": None, "upscale_factor": None, "supported_sizes": None,
     "allowed_passthrough_parameters": [],
     "pricing_skus": {"duration_seconds_480p": "0.05", "duration_seconds_720p": "0.10", "duration_seconds_1080p": "0.15"}},
    {"id": "bytedance/seedance-1.5-pro", "name": "ByteDance: Seedance 1.5 Pro", "canonical_slug": "bytedance/seedance-1.5-pro",
     "created": NOW - 900_000, "supported_durations": [5, 10], "supported_resolutions": ["480p", "720p", "1080p"],
     "supported_aspect_ratios": ["16:9"], "supported_frame_images": ["first_frame", "last_frame"],
     "generate_audio": False, "seed": True, "creativity": None, "upscale_factor": None, "supported_sizes": None,
     "allowed_passthrough_parameters": [], "pricing_skus": {"cents_per_second_output_720p": "6", "cents_per_second_output_1080p": "12"}},
]


def _json(data: Any, status: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=data, headers=headers)


def _err(status: int, message: str) -> httpx.Response:
    return _json({"error": {"code": status, "message": message}}, status)


class FakeOpenRouter:
    def __init__(self, *, credits_enabled: bool = False, key_limit: float | None = 10.0):
        self.calls: list[tuple[str, str, Any]] = []
        self.generations: dict[str, dict[str, Any]] = {}
        self.videos: dict[str, dict[str, Any]] = {}
        self.failures: dict[str, list[int]] = {}
        self.credits_enabled = credits_enabled
        self.key_limit = key_limit
        self.spent = 0.0
        self._lock = threading.Lock()
        self._video_cache: dict[int, bytes] = {}

    # ---------------------------------------------------------- utilidades de teste

    def fail(self, route: str, status: int, times: int = 1) -> None:
        """Faz a rota ("POST /images") responder com erro `status` nas próximas `times` chamadas."""
        self.failures.setdefault(route, []).extend([status] * times)

    def count(self, route: str) -> int:
        method, path = route.split(" ", 1)
        return sum(1 for m, p, _ in self.calls if m == method and p == path)

    def _gen(self, prefix: str, cost: float, **extra: Any) -> str:
        gid = f"gen-{prefix}{int(time.time())}-{uuid.uuid4().hex[:20]}"
        with self._lock:
            self.generations[gid] = {"id": gid, "total_cost": round(cost, 8), **extra}
            self.spent += cost
        return gid

    # ---------------------------------------------------------- roteamento

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        path = path[path.index("/api/v1") + 7:] if "/api/v1" in path else path
        body = None
        if request.content:
            try:
                body = json.loads(request.content)
            except ValueError:
                body = None
        with self._lock:
            self.calls.append((request.method, path, body))
            queued = self.failures.get(f"{request.method} {path}") or []
            status = queued.pop(0) if queued else None
        if status:
            return _err(status, f"falha simulada {status}")
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or not auth[7:]:
            return _err(401, "No auth credentials found")
        m = request.method
        if m == "GET" and path == "/models":
            mod = request.url.params.get("output_modalities")
            data = {"text": TEXT_MODELS, "image": CHAT_IMAGE_MODELS, "speech": SPEECH_MODELS}.get(mod or "text", [])
            return _json({"data": data, "links": {}, "total_count": len(data)})
        if m == "GET" and path == "/images/models":
            return _json({"data": IMAGE_MODELS})
        if m == "GET" and path.startswith("/images/models/") and path.endswith("/endpoints"):
            mid = path[len("/images/models/"):-len("/endpoints")]
            if mid not in IMAGE_PRICING:
                return _err(404, "model not found")
            caps = next(x for x in IMAGE_MODELS if x["id"] == mid)["supported_parameters"]
            return _json({"id": mid, "endpoints": [{
                "provider_name": "Google", "provider_slug": "google-ai-studio", "provider_tag": None,
                "pricing": IMAGE_PRICING[mid], "supported_parameters": caps, "allowed_passthrough_parameters": [],
                "supports_streaming": False}]})
        if m == "GET" and path == "/videos/models":
            return _json({"data": VIDEO_MODELS})
        if m == "GET" and path == "/key":
            usage = round(self.spent, 6)
            return _json({"data": {"label": "sk-or-v1-fak...", "usage": usage, "usage_daily": usage,
                                   "usage_weekly": usage, "usage_monthly": usage, "limit": self.key_limit,
                                   "limit_remaining": None if self.key_limit is None else round(self.key_limit - usage, 6),
                                   "limit_reset": None, "is_free_tier": False}})
        if m == "GET" and path == "/credits":
            if not self.credits_enabled:
                return _err(403, "Only management keys can fetch credits")
            return _json({"data": {"total_credits": 25.0, "total_usage": round(self.spent, 6)}})
        if m == "GET" and path == "/generation":
            gid = request.url.params.get("id", "")
            info = self.generations.get(gid)
            return _json({"data": info}) if info else _err(404, "Generation not found")
        if m == "POST" and path == "/chat/completions":
            return self._chat(body or {})
        if m == "POST" and path == "/images":
            return self._image(body or {})
        if m == "POST" and path == "/audio/speech":
            return self._speech(body or {})
        if m == "POST" and path == "/videos":
            return self._video_submit(body or {})
        if m == "GET" and re.fullmatch(r"/videos/[^/]+", path):
            return self._video_status(path.split("/")[2])
        if m == "GET" and re.fullmatch(r"/videos/[^/]+/content", path):
            return self._video_content(path.split("/")[2])
        return _err(404, f"rota desconhecida {m} {path}")

    # ---------------------------------------------------------- texto

    @staticmethod
    def _model_prices(model: str) -> tuple[float, float]:
        for item in TEXT_MODELS + CHAT_IMAGE_MODELS:
            if item["id"] == model:
                return float(item["pricing"]["prompt"]), float(item["pricing"]["completion"])
        return 0.000001, 0.000002

    def _chat(self, body: dict[str, Any]) -> httpx.Response:
        model = body.get("model", "")
        messages = body.get("messages") or []
        prompt_text = "\n".join(str(m.get("content", "")) for m in messages)
        if "image" in (body.get("modalities") or []):
            png = self._png(prompt_text)
            content = None
            images = [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}]
            pt, ct = len(prompt_text) // 4, 1290
            p_in, p_out = self._model_prices(model)
            cost = pt * p_in + ct * p_out
            gid = self._gen("", cost)
            return _json({"id": gid, "model": model, "choices": [{"index": 0, "finish_reason": "stop",
                          "message": {"role": "assistant", "content": content, "images": images}}],
                          "usage": {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct, "cost": cost}})
        fmt = body.get("response_format") or {}
        name = ((fmt.get("json_schema") or {}).get("name")) or self._guess_task(prompt_text)
        user = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
        data = self._answer(name, str(user), prompt_text)
        content = json.dumps(data, ensure_ascii=False)
        pt = max(1, len(prompt_text) // 4)
        ct = max(1, len(content) // 4)
        p_in, p_out = self._model_prices(model)
        cost = pt * p_in + ct * p_out
        gid = self._gen("", cost, tokens_prompt=pt, tokens_completion=ct)
        return _json({
            "id": gid, "object": "chat.completion", "created": int(time.time()), "model": model,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct, "cost": round(cost, 8),
                      "completion_tokens_details": {"reasoning_tokens": 0}},
        })

    @staticmethod
    def _guess_task(text: str) -> str:
        for key, name in (("SENTENCES", "scene_plan"), ("REDESIGN", "scene_rewrite"), ("thumbnail concepts", "thumbnail_concepts"),
                          ("titles:", "video_metadata"), ("NEW learnings", "learnings"), ("Skill", "skill_document")):
            if key in text:
                return name
        return "script_analysis"

    def _answer(self, name: str, user: str, full: str) -> dict[str, Any]:
        if name == "script_analysis":
            first = re.search(r"## SCRIPT\n(.{0,80})", user, re.S)
            excerpt = (first.group(1) if first else "").strip() or "início"
            return {
                "summary": "Documentário sobre um mistério histórico com boa progressão.",
                "verdict": "needs_revision",
                "scores": {"hook": 7, "structure": 8, "coherence": 8, "retention": 7, "originality": 8, "channel_fit": 9},
                "hook_assessment": "O gancho apresenta o mistério cedo, mas poderia ser mais direto.",
                "structure": [{"title": "Abertura", "starts_with": excerpt[:40], "assessment": "Boa contextualização."}],
                "ending_assessment": "Final conclusivo.", "pacing_assessment": "Ritmo adequado para a duração.",
                "issues": [{"type": "hook", "severity": "medium", "excerpt": excerpt[:60],
                            "explanation": "A primeira frase demora a chegar no conflito.",
                            "suggestion": "Comece pela pergunta central."}],
                "repetition_notes": [], "policy_risks": [],
                "originality_assessment": "Texto original.", "channel_fit_assessment": "Alinhado ao canal.",
                "improvements": ["Encurtar a introdução", "Adicionar um loop aberto no meio"],
            }
        if name == "scene_plan":
            block = user.split("## SENTENCES", 1)[-1]
            idx = [int(x) for x in re.findall(r"^\[(\d+)\]", block, re.M)]
            allow_video = "Do NOT use VIDEO" not in user
            scenes = []
            for n, i in enumerate(range(0, len(idx), 2)):
                start, end = idx[i], idx[min(i + 1, len(idx) - 1)]
                vid = allow_video and n % 4 == 3
                scenes.append({
                    "start": start, "end": end,
                    "visual_description": f"Plano cinematográfico da cena {start}.",
                    "prompt": f"Cinematic wide shot, scene {start}, moody volumetric light, 35mm film grain",
                    "asset_type": "VIDEO" if vid else "IMAGE_MOTION",
                    "asset_type_reason": "Momento de impacto." if vid else "Imagem com movimento lento.",
                    "motion": ["zoom_in", "pan_right", "zoom_out", "pan_left"][n % 4],
                })
            return {"scenes": scenes}
        if name == "scene_rewrite":
            return {"visual_description": "Novo enquadramento em close.", "prompt": "Dramatic close-up, rim light, fog",
                    "asset_type": "IMAGE_MOTION", "asset_type_reason": "Close com zoom lento.", "motion": "zoom_in"}
        if name == "thumbnail_concepts":
            count = int((re.search(r"Create (\d+) DISTINCT", user) or [0, 3])[1])
            return {"concepts": [{
                "name": f"Conceito {i + 1}", "idea": "Objeto misterioso iluminado.", "emotion": "curiosidade",
                "composition": "Objeto à direita, espaço para texto à esquerda.", "overlay_text": f"SEGREDO {i + 1}",
                "prompt": f'Mysterious artifact in darkness, rim light, text "SEGREDO {i + 1}"', "rationale": "Gera curiosidade.",
            } for i in range(count)]}
        if name == "video_metadata":
            scenes = [int(x) for x in re.findall(r"^(\d+) ·", user, re.M)] or [1]
            picks = sorted({scenes[0], *scenes[len(scenes) // 3::max(1, len(scenes) // 3)]})
            return {
                "titles": [{"title": f"O Segredo Que Ninguém Contou #{i}", "angle": "curiosidade"} for i in range(1, 9)],
                "description": "Neste vídeo revelamos um mistério esquecido pela história.\n\nAssista até o fim.",
                "chapters": [{"scene": s, "title": f"Parte {n + 1}"} for n, s in enumerate(picks)],
                "tags": ["mistério", "história", "documentário", "segredos", "curiosidades"],
                "hashtags": ["#historia", "#misterio", "#documentario"],
                "primary_keywords": ["mistério histórico"], "secondary_keywords": ["segredos da história"],
                "policy_notes": [],
            }
        if name == "learnings":
            return {"learnings": [
                {"category": "visuals", "text": "Preferir closes dramáticos com luz de recorte.", "rationale": "O dono reescreveu cenas pedindo closes."},
                {"category": "metadata", "text": "Usar títulos com pergunta direta.", "rationale": "Título escolhido era uma pergunta."},
            ]}
        if name == "skill_document":
            return {"content": "# Skill\n\n## Direção visual\n- Preferir closes dramáticos.\n", "summary": "Skill atualizada."}
        return {}

    # ---------------------------------------------------------- mídia

    @staticmethod
    def _png(prompt: str, size: tuple[int, int] = (1344, 768)) -> bytes:
        digest = hashlib.sha256(prompt.encode()).digest()
        im = Image.new("RGB", size, (digest[0] // 3, digest[1] // 3, digest[2] // 3))
        d = ImageDraw.Draw(im)
        d.rectangle([40, 40, size[0] - 40, size[1] - 40], outline=(240, 170, 60), width=6)
        d.text((80, 80), prompt[:90], fill=(240, 230, 210))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return buf.getvalue()

    def _image(self, body: dict[str, Any]) -> httpx.Response:
        model = body.get("model", "")
        if not any(x["id"] == model for x in IMAGE_MODELS):
            return _err(404, f"image model {model} not found")
        price = IMAGE_PRICING[model]
        res = body.get("resolution")
        entry = next((p for p in price if p.get("variant") == res), price[0])
        cost = entry["cost_usd"]
        gid = self._gen("img-", cost)
        png = self._png(body.get("prompt", ""))
        return _json({"created": int(time.time()), "data": [{"b64_json": base64.b64encode(png).decode(), "media_type": "image/png"}],
                      "usage": {"prompt_tokens": 50, "completion_tokens": 1290, "total_tokens": 1340, "cost": cost}},
                     headers={"X-Generation-Id": gid})

    @staticmethod
    def _mp3(seconds: float) -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "a.mp3"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            f"sine=frequency=220:duration={seconds:.2f}", "-c:a", "libmp3lame", "-b:a", "64k", str(out)],
                           check=True)
            return out.read_bytes()

    def _speech(self, body: dict[str, Any]) -> httpx.Response:
        model = body.get("model", "")
        info = next((x for x in SPEECH_MODELS if x["id"] == model), None)
        if info is None:
            return _err(404, f"speech model {model} not found")
        voice = body.get("voice")
        if voice and voice not in info["supported_voices"]:
            return _err(400, f"voice {voice} not supported")
        text = str(body.get("input", ""))
        seconds = max(1.0, len(text) / 15.0) / float(body.get("speed") or 1.0)
        p_in, p_out = float(info["pricing"]["prompt"]), float(info["pricing"]["completion"])
        cost = len(text) * p_in if not p_out else (len(text) / 4) * p_in + seconds * 32 * p_out
        gid = self._gen("tts-", cost)
        return httpx.Response(200, content=self._mp3(seconds), headers={"Content-Type": "audio/mpeg", "X-Generation-Id": gid})

    def _video_submit(self, body: dict[str, Any]) -> httpx.Response:
        model = body.get("model", "")
        info = next((x for x in VIDEO_MODELS if x["id"] == model), None)
        if info is None:
            return _err(404, f"video model {model} not found")
        duration = int(body.get("duration") or 5)
        if duration not in info["supported_durations"]:
            return _err(400, f"duration {duration} not supported")
        vid = f"gen-vid-{int(time.time())}-{uuid.uuid4().hex[:20]}"
        res = body.get("resolution") or "720p"
        skus = info["pricing_skus"]
        if "duration_seconds_without_audio" in skus:
            per_s = float(skus["duration_seconds_with_audio" if body.get("generate_audio") else "duration_seconds_without_audio"])
        elif f"duration_seconds_{res}" in skus:
            per_s = float(skus[f"duration_seconds_{res}"])
        else:
            per_s = float(skus.get(f"cents_per_second_output_{res}", "6")) / 100
        self.videos[vid] = {"polls": 0, "duration": duration, "cost": per_s * duration, "model": model}
        return _json({"id": vid, "polling_url": f"/api/v1/videos/{vid}", "status": "pending"})

    def _video_status(self, vid: str) -> httpx.Response:
        job = self.videos.get(vid)
        if job is None:
            return _err(404, "video job not found")
        job["polls"] += 1
        if job["polls"] < 2:
            return _json({"id": vid, "polling_url": f"/api/v1/videos/{vid}", "status": "in_progress"})
        if "generation_id" not in job:
            job["generation_id"] = self._gen("vid-", job["cost"])
        return _json({"id": vid, "polling_url": f"/api/v1/videos/{vid}", "status": "completed",
                      "generation_id": job["generation_id"], "unsigned_urls": [f"https://cdn.example/{vid}.mp4"],
                      "usage": {"cost": round(job["cost"], 6), "is_byok": False}})

    def _video_content(self, vid: str) -> httpx.Response:
        job = self.videos.get(vid)
        if job is None:
            return _err(404, "video job not found")
        duration = job["duration"]
        if duration not in self._video_cache:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "v.mp4"
                subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                                f"testsrc=size=640x360:rate=24:duration={duration}", "-pix_fmt", "yuv420p",
                                "-c:v", "libx264", "-preset", "ultrafast", str(out)], check=True)
                self._video_cache[duration] = out.read_bytes()
        return httpx.Response(200, content=self._video_cache[duration], headers={"Content-Type": "video/mp4"})


def asgi_app(fake: FakeOpenRouter):
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.routing import Route

    async def endpoint(request: Request) -> Response:
        body = await request.body()
        req = httpx.Request(request.method, str(request.url), headers=request.headers.raw, content=body)
        resp = fake.handler(req)
        headers = {k: v for k, v in resp.headers.items() if k.lower() not in ("content-length", "content-encoding")}
        return Response(content=resp.content, status_code=resp.status_code, headers=headers)

    return Starlette(routes=[Route("/{path:path}", endpoint, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])])


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9911)
    args = parser.parse_args()
    uvicorn.run(asgi_app(FakeOpenRouter()), host="127.0.0.1", port=args.port, log_level="warning")
