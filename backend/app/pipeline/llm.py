"""Chamada de modelos de texto com resposta JSON validada (com uma tentativa de correção)."""

from __future__ import annotations

import copy
import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from ..jobs.context import JobContext
from ..providers import registry
from ..providers.base import LLMResult, ProviderError

T = TypeVar("T", bound=BaseModel)


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON Schema compatível com 'structured outputs' estrito (sem $ref, tudo obrigatório)."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].split("/")[-1]
                return resolve(copy.deepcopy(defs[name]))
            # "title"/"default" são metadados do schema — mas dentro de "properties" são NOMES de campos
            # (ex.: o título do vídeo) e precisam ficar
            out = {k: ({pk: resolve(pv) for pk, pv in v.items()} if k == "properties" and isinstance(v, dict)
                       else resolve(v))
                   for k, v in node.items() if k not in ("title", "default")}
            if out.get("type") == "object" and "properties" in out:
                out["required"] = list(out["properties"].keys())
                out["additionalProperties"] = False
            return out
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


def parse_json_loose(text: str) -> Any:
    raw = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    try:
        return json.loads(raw)
    except ValueError:
        pass
    starts = [i for i in (raw.find("{"), raw.find("[")) if i != -1]
    if not starts:
        raise ValueError("resposta sem JSON")
    start = min(starts)
    end = max(raw.rfind("}"), raw.rfind("]"))
    candidate = raw[start:end + 1]
    try:
        return json.loads(candidate)
    except ValueError:
        cleaned = re.sub(r",\s*([}\]])", r"\1", candidate)
        return json.loads(cleaned)


def call_json(
    ctx: JobContext,
    *,
    model: str,
    system: str,
    user: str,
    schema: type[T],
    schema_name: str,
    temperature: float | None = 0.4,
    max_tokens: int | None = 8000,
    reasoning: str | None = None,
    output_units: float | None = None,
    stage: str | None = None,
) -> tuple[T, LLMResult]:
    provider, model_id = registry.split_ref(model)
    llm = registry.llm(provider)
    json_schema = strict_schema(schema)
    # o schema também vai no texto: nem todo provedor aplica o 'structured outputs' (modo JSON simples)
    schema_text = json.dumps(json_schema, ensure_ascii=False, separators=(",", ":"))
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": (
            f"{system}\n\nAnswer with ONE JSON object that follows this JSON Schema exactly — same field names, "
            f"every field present:\n{schema_text}"
        )},
        {"role": "user", "content": user},
    ]
    session_id = f"dm-project-{ctx.project_id}" if ctx.project_id else f"dm-channel-{ctx.channel_id}"
    meta = {"schema": schema_name}
    if output_units:
        meta["output_units"] = output_units

    def run() -> LLMResult:
        ctx.check_cancel()
        res = llm.complete(model=model_id, messages=messages, json_schema=json_schema, schema_name=schema_name,
                           temperature=temperature, max_tokens=max_tokens, reasoning_effort=reasoning,
                           session_id=session_id)
        ctx.record_now(res.usage, stage=stage, meta=meta)
        return res

    result = run()
    try:
        return schema.model_validate(parse_json_loose(result.text)), result
    except (ValueError, ValidationError) as exc:
        problem = str(exc)[:1500]
    if result.finish_reason == "length":
        problem = "a resposta foi cortada por limite de tamanho; responda de forma mais concisa. " + problem
    messages += [
        {"role": "assistant", "content": result.text[:30000]},
        {"role": "user", "content": (
            "Your previous answer was not valid JSON for the required schema. Problem: "
            f"{problem}\nReturn ONLY the corrected JSON object, with every required field, no commentary."
        )},
    ]
    result = run()
    try:
        return schema.model_validate(parse_json_loose(result.text)), result
    except (ValueError, ValidationError) as exc:
        raise ProviderError(f"O modelo {model_id} retornou um JSON inválido duas vezes: {str(exc)[:300]}",
                            retryable=True) from exc
