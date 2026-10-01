"""Etapa 1 — análise do roteiro (estrutura, coerência, repetição, duração, adequação e riscos)."""

from __future__ import annotations

from ..db import session_scope
from ..jobs.context import JobContext, handler
from ..models import utcnow
from .. import tiers
from . import prompts, text
from .common import StageError, load_project, model_for
from .context import full_context
from .llm import call_json
from .schemas import ScriptAnalysis


@handler("script.analyze")
def analyze_script(ctx: JobContext) -> dict:
    with session_scope() as db:
        project = load_project(db, ctx.project_id)
        channel = project.channel
        script = project.script or ""
        if len(text.words(script)) < 30:
            raise StageError("O roteiro está vazio ou curto demais para analisar (mínimo de 30 palavras).")
        tier = project.quality
        model = model_for(db, "text", tier)
        params = tiers.tier_params(db, tier)
        wpm = channel.words_per_minute or text.default_wpm(channel.language)
        metrics = text.script_metrics(script, wpm, channel.duration_min, channel.duration_max)
        system, user = prompts.script_analysis(full_context(db, project), script, metrics,
                                               text.language_label(channel.language))
        script_hash = text.content_hash(script)
    ctx.progress(0.15, f"analisando roteiro ({metrics['words']} palavras) com {model}", force=True)
    result, llm = call_json(ctx, model=model, system=system, user=user, schema=ScriptAnalysis,
                            schema_name="script_analysis", temperature=0.2, max_tokens=12000,
                            reasoning=params.get("reasoning"))
    with session_scope() as db:
        project = load_project(db, ctx.project_id)
        project.analysis = {
            "metrics": metrics,
            "ai": result.model_dump(),
            "model": llm.model,
            "created_at": utcnow().isoformat() + "Z",
        }
        project.analysis_at = utcnow()
        project.analysis_script_hash = script_hash
        if project.status == "draft":
            project.status = "script"
    labels = {"approved": "aprovado", "needs_revision": "precisa de revisão", "high_risk": "alto risco"}
    return {"message": f"análise concluída: {labels.get(result.verdict, result.verdict)}", "verdict": result.verdict}
