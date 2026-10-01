"""Formatos de resposta (JSON estruturado) pedidos aos modelos de texto."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _enum(*values: str):
    return Field(json_schema_extra={"enum": list(values)})


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


class Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


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
    type: str = _enum(*ISSUE_TYPES)
    severity: str = _enum(*SEVERITY)
    excerpt: str
    explanation: str
    suggestion: str

    @field_validator("type", mode="before")
    @classmethod
    def _t(cls, v):
        return _norm(v, ISSUE_TYPES, "other")

    @field_validator("severity", mode="before")
    @classmethod
    def _s(cls, v):
        return _norm(v, SEVERITY, "medium")


class PolicyRisk(Lenient):
    category: str = _enum(*RISK_CATEGORIES)
    severity: str = _enum(*SEVERITY)
    excerpt: str
    explanation: str
    recommendation: str

    @field_validator("category", mode="before")
    @classmethod
    def _c(cls, v):
        return _norm(v, RISK_CATEGORIES, "other")

    @field_validator("severity", mode="before")
    @classmethod
    def _s(cls, v):
        return _norm(v, SEVERITY, "medium")


class Scores(Lenient):
    hook: int
    structure: int
    coherence: int
    retention: int
    originality: int
    channel_fit: int


class Section(Lenient):
    title: str
    starts_with: str
    assessment: str


class ScriptAnalysis(Lenient):
    summary: str
    verdict: str = _enum("approved", "needs_revision", "high_risk")
    scores: Scores
    hook_assessment: str
    structure: list[Section]
    ending_assessment: str
    pacing_assessment: str
    issues: list[Issue]
    repetition_notes: list[str]
    policy_risks: list[PolicyRisk]
    originality_assessment: str
    channel_fit_assessment: str
    improvements: list[str]

    @field_validator("verdict", mode="before")
    @classmethod
    def _v(cls, v):
        return _norm(v, ("approved", "needs_revision", "high_risk"), "needs_revision")


class PlannedScene(Lenient):
    start: int
    end: int
    visual_description: str
    prompt: str
    asset_type: str = _enum(*ASSET_TYPES)
    asset_type_reason: str
    motion: str = _enum(*MOTIONS)

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


class SceneRewrite(Lenient):
    visual_description: str
    prompt: str
    asset_type: str = _enum(*ASSET_TYPES)
    asset_type_reason: str
    motion: str = _enum(*MOTIONS)

    @field_validator("asset_type", mode="before")
    @classmethod
    def _a(cls, v):
        return _norm(v, ASSET_TYPES, "IMAGE_MOTION")

    @field_validator("motion", mode="before")
    @classmethod
    def _m(cls, v):
        return _norm(v, MOTIONS, "zoom_in")


class ThumbConcept(Lenient):
    name: str
    idea: str
    emotion: str
    composition: str
    overlay_text: str
    prompt: str
    rationale: str


class ThumbConcepts(Lenient):
    concepts: list[ThumbConcept]


class TitleOption(Lenient):
    title: str
    angle: str


class Chapter(Lenient):
    scene: int
    title: str


class VideoMetadata(Lenient):
    titles: list[TitleOption]
    description: str
    chapters: list[Chapter]
    tags: list[str]
    hashtags: list[str]
    primary_keywords: list[str]
    secondary_keywords: list[str]
    policy_notes: list[str]


class Learning(Lenient):
    category: str = _enum(*LEARNING_CATEGORIES)
    text: str
    rationale: str

    @field_validator("category", mode="before")
    @classmethod
    def _c(cls, v):
        return _norm(v, LEARNING_CATEGORIES, "general")


class Learnings(Lenient):
    learnings: list[Learning]


class SkillDocument(Lenient):
    content: str
    summary: str
