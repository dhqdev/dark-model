"""Formatos de resposta (JSON estruturado) pedidos aos modelos de texto.

O schema enviado ao modelo exige todos os campos; a validação daqui é tolerante (nem todo modelo
respeita o schema à risca): campo de texto/lista ausente vira vazio, sinônimos de nomes de campo são
aceitos, texto onde se esperava lista (e vice-versa) é convertido e itens inválidos de uma lista são
descartados — só campos essenciais (ex.: início/fim de uma cena) continuam obrigatórios.
"""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


def _enum(*values: str, default: str | None = None):
    if default is None:
        return Field(json_schema_extra={"enum": list(values)})
    return Field(default=default, json_schema_extra={"enum": list(values)})


SEVERITY = ("low", "medium", "high")
ASSET_TYPES = ("IMAGE", "VIDEO", "IMAGE_MOTION")
MOTIONS = ("zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "static")
ISSUE_TYPES = ("structure", "coherence", "repetition", "pacing", "clarity", "factual", "length", "style", "hook",
               "ending", "other")
RISK_CATEGORIES = (
    "copyright", "reused_content", "inauthentic_content", "spam_deceptive", "misinformation",
    "violence_graphic", "hate_harassment", "sexual_content", "dangerous_activities",
    "medical_financial_claims", "child_safety", "privacy", "synthetic_disclosure", "advertiser_unfriendly", "other",
)
LEARNING_CATEGORIES = ("script", "scenes", "visuals", "narration", "thumbnail", "metadata", "general")


def _key(name: object) -> str:
    return re.sub(r"[\s\-]+", "_", str(name).strip()).lower()


def _as_text(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(_as_text(v) for v in value if v not in (None, ""))
    if isinstance(value, dict):
        parts = [str(v) for v in value.values() if isinstance(v, (str, int, float)) and str(v).strip()]
        return " — ".join(parts) if parts else json.dumps(value, ensure_ascii=False)
    return str(value)


class Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")
    # nomes alternativos que os modelos costumam usar para um campo
    ALIASES: ClassVar[dict[str, tuple[str, ...]]] = {}

    @model_validator(mode="before")
    @classmethod
    def _lenient(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        raw = {_key(k): v for k, v in data.items()}
        out: dict[str, Any] = {}
        for name, field in cls.model_fields.items():
            value = raw.get(name)
            if value in (None, ""):
                for alias in cls.ALIASES.get(name, ()):
                    if raw.get(alias) not in (None, "", []):
                        value = raw[alias]
                        break
            if value is None:
                continue  # vale o padrão do campo (ou erro, se for essencial)
            ann = field.annotation
            if ann is str and not isinstance(value, str):
                value = _as_text(value)
            elif get_origin(ann) is list:
                item = (get_args(ann) or (Any,))[0]
                if not isinstance(value, list):
                    value = [_as_text(value)] if item is str and value != "" else []
                elif item is str:
                    value = [_as_text(v) for v in value if v not in (None, "")]
                elif isinstance(item, type) and issubclass(item, Lenient):
                    kept = []
                    for v in value:
                        try:
                            kept.append(item.model_validate(v))
                        except ValidationError:
                            continue
                    # se nenhum item serve, mantém o original para o erro aparecer (e o modelo corrigir)
                    value = kept if kept or not value else value
            out[name] = value
        return out


def _norm(value: object, allowed: tuple[str, ...], default: str) -> str:
    v = str(value or "").strip()
    for a in allowed:
        if v.lower() == a.lower():
            return a
    v2 = v.upper().replace(" ", "_").replace("+", "_").replace("-", "_")
    for a in allowed:
        if v2 == a.upper():
            return a
    return default


class Issue(Lenient):
    type: str = _enum(*ISSUE_TYPES, default="other")
    severity: str = _enum(*SEVERITY, default="medium")
    excerpt: str = ""
    explanation: str = ""
    suggestion: str = ""

    @field_validator("type", mode="before")
    @classmethod
    def _t(cls, v):
        return _norm(v, ISSUE_TYPES, "other")

    @field_validator("severity", mode="before")
    @classmethod
    def _s(cls, v):
        return _norm(v, SEVERITY, "medium")


class PolicyRisk(Lenient):
    category: str = _enum(*RISK_CATEGORIES, default="other")
    severity: str = _enum(*SEVERITY, default="medium")
    excerpt: str = ""
    explanation: str = ""
    recommendation: str = ""

    @field_validator("category", mode="before")
    @classmethod
    def _c(cls, v):
        return _norm(v, RISK_CATEGORIES, "other")

    @field_validator("severity", mode="before")
    @classmethod
    def _s(cls, v):
        return _norm(v, SEVERITY, "medium")


def _score(value: Any) -> Any:
    """'8', '8/10', 7.5 → inteiro de 0 a 10; ausente/ilegível → None (não inventa nota)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return max(0, min(10, round(value)))
    m = re.search(r"\d+(?:[.,]\d+)?", str(value))
    return max(0, min(10, round(float(m.group().replace(",", "."))))) if m else None


class Scores(Lenient):
    # nota ausente fica None (o schema pede inteiro; a validação não inventa nota)
    hook: int = None  # type: ignore[assignment]
    structure: int = None  # type: ignore[assignment]
    coherence: int = None  # type: ignore[assignment]
    retention: int = None  # type: ignore[assignment]
    originality: int = None  # type: ignore[assignment]
    channel_fit: int = None  # type: ignore[assignment]
    ALIASES: ClassVar[dict[str, tuple[str, ...]]] = {
        "retention": ("retention_potential",), "channel_fit": ("fit", "channel"),
    }

    @model_validator(mode="before")
    @classmethod
    def _n(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = {k: n for k, v in data.items() if (n := _score(v)) is not None}
        return data


class Section(Lenient):
    title: str = ""
    starts_with: str = ""
    assessment: str = ""
    ALIASES: ClassVar[dict[str, tuple[str, ...]]] = {
        "title": ("name", "section", "heading", "part", "label", "section_title"),
        "starts_with": ("start", "begins_with", "opening", "first_words", "start_text"),
        "assessment": ("evaluation", "analysis", "comment", "comments", "notes", "feedback", "description"),
    }

    @model_validator(mode="after")
    def _title(self):
        if not self.title.strip() and self.starts_with.strip():
            words = self.starts_with.split()
            self.title = " ".join(words[:6]) + ("…" if len(words) > 6 else "")
        return self


class ScriptAnalysis(Lenient):
    summary: str = ""
    verdict: str = _enum("approved", "needs_revision", "high_risk", default="needs_revision")
    scores: Scores = Field(default_factory=Scores)
    hook_assessment: str = ""
    structure: list[Section] = []
    ending_assessment: str = ""
    pacing_assessment: str = ""
    issues: list[Issue] = []
    repetition_notes: list[str] = []
    policy_risks: list[PolicyRisk] = []
    originality_assessment: str = ""
    channel_fit_assessment: str = ""
    improvements: list[str] = []
    ALIASES: ClassVar[dict[str, tuple[str, ...]]] = {
        "structure": ("sections",), "policy_risks": ("risks", "youtube_risks"), "improvements": ("suggestions",),
    }

    @field_validator("verdict", mode="before")
    @classmethod
    def _v(cls, v):
        return _norm(v, ("approved", "needs_revision", "high_risk"), "needs_revision")


class PlannedScene(Lenient):
    start: int
    end: int
    visual_description: str = ""
    prompt: str
    asset_type: str = _enum(*ASSET_TYPES, default="IMAGE_MOTION")
    asset_type_reason: str = ""
    motion: str = _enum(*MOTIONS, default="zoom_in")
    ALIASES: ClassVar[dict[str, tuple[str, ...]]] = {
        "start": ("from", "first", "start_sentence", "start_index"),
        "end": ("to", "last", "end_sentence", "end_index"),
        "prompt": ("image_prompt", "visual_prompt"),
        "visual_description": ("description", "visual"),
    }

    @field_validator("asset_type", mode="before")
    @classmethod
    def _a(cls, v):
        return _norm(v, ASSET_TYPES, "IMAGE_MOTION")

    @field_validator("motion", mode="before")
    @classmethod
    def _m(cls, v):
        return _norm(v, MOTIONS, "zoom_in")


class ScenePlan(Lenient):
    scenes: list[PlannedScene]
    ALIASES: ClassVar[dict[str, tuple[str, ...]]] = {"scenes": ("scene_plan", "items")}


class SceneRewrite(Lenient):
    visual_description: str = ""
    prompt: str
    asset_type: str = _enum(*ASSET_TYPES, default="IMAGE_MOTION")
    asset_type_reason: str = ""
    motion: str = _enum(*MOTIONS, default="zoom_in")
    ALIASES: ClassVar[dict[str, tuple[str, ...]]] = {"prompt": ("image_prompt", "visual_prompt")}

    @field_validator("asset_type", mode="before")
    @classmethod
    def _a(cls, v):
        return _norm(v, ASSET_TYPES, "IMAGE_MOTION")

    @field_validator("motion", mode="before")
    @classmethod
    def _m(cls, v):
        return _norm(v, MOTIONS, "zoom_in")


class ThumbConcept(Lenient):
    name: str = ""
    idea: str = ""
    emotion: str = ""
    composition: str = ""
    overlay_text: str = ""
    prompt: str
    rationale: str = ""
    ALIASES: ClassVar[dict[str, tuple[str, ...]]] = {
        "prompt": ("image_prompt",), "overlay_text": ("text", "headline"), "name": ("title",),
    }


class ThumbConcepts(Lenient):
    concepts: list[ThumbConcept]


class TitleOption(Lenient):
    title: str
    angle: str = ""


class Chapter(Lenient):
    scene: int
    title: str


class VideoMetadata(Lenient):
    titles: list[TitleOption]
    description: str = ""
    chapters: list[Chapter] = []
    tags: list[str] = []
    hashtags: list[str] = []
    primary_keywords: list[str] = []
    secondary_keywords: list[str] = []
    policy_notes: list[str] = []


class Learning(Lenient):
    category: str = _enum(*LEARNING_CATEGORIES, default="general")
    text: str
    rationale: str = ""

    @field_validator("category", mode="before")
    @classmethod
    def _c(cls, v):
        return _norm(v, LEARNING_CATEGORIES, "general")


class Learnings(Lenient):
    learnings: list[Learning] = []


class SkillDocument(Lenient):
    content: str
    summary: str = ""
