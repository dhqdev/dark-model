export type Quality = "ECONOMY" | "BALANCED" | "PREMIUM";
export type AssetType = "IMAGE" | "VIDEO" | "IMAGE_MOTION";
export type Motion = "zoom_in" | "zoom_out" | "pan_left" | "pan_right" | "pan_up" | "pan_down" | "static";
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "canceled";

export interface Channel {
  id: number;
  name: string;
  slug: string;
  language: string;
  country: string;
  audience: string;
  niche: string;
  style: string;
  tone: string;
  duration_min: number;
  duration_max: number;
  words_per_minute: number | null;
  default_wpm: number;
  scene_seconds: number;
  visual_style: string;
  default_quality: Quality;
  tts_model: string | null;
  tts_voice: string | null;
  tts_speed: number;
  tts_style: string;
  thumbnail_style: string;
  thumbnail_text_mode: "in_image" | "none";
  auto_learn: boolean;
  notes: string;
  archived: boolean;
  created_at: string;
  updated_at: string;
  stats: { projects?: number; cost?: number; skill_version?: number; pending_learnings?: number };
}

export interface Asset {
  id: number;
  kind: string;
  url: string;
  mime: string;
  size: number;
  width: number | null;
  height: number | null;
  duration: number | null;
  provider: string;
  model: string;
  cost: number | null;
  prompt: string;
  params: Record<string, unknown>;
  scene_id: number | null;
  concept_id: number | null;
  created_at: string;
}

export interface Scene {
  id: number;
  position: number;
  narration: string;
  est_duration: number;
  audio_duration: number | null;
  duration: number;
  start: number;
  words: number;
  visual_description: string;
  prompt: string;
  asset_type: AssetType;
  ai_asset_type: AssetType;
  asset_type_reason: string;
  motion: Motion;
  locked: boolean;
  notes: string;
  image: Asset | null;
  clip: Asset | null;
  audio: Asset | null;
  image_ok: boolean;
  clip_ok: boolean;
  visual_ready: boolean;
  audio_ok: boolean;
}

export interface Job {
  id: number;
  kind: string;
  stage: string;
  lane: string;
  label: string;
  status: JobStatus;
  project_id: number | null;
  channel_id: number | null;
  scene_id: number | null;
  target_id: number | null;
  parent_id: number | null;
  is_group: boolean;
  progress: number;
  message: string;
  error: string;
  attempts: number;
  max_attempts: number;
  cost: number;
  result: Record<string, unknown> | null;
  cancel_requested: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  run_after: string | null;
  project_title?: string | null;
  channel_name?: string | null;
  children?: Job[];
}

export interface Issue {
  type: string;
  severity: "low" | "medium" | "high";
  excerpt: string;
  explanation: string;
  suggestion: string;
}

export interface PolicyRisk {
  category: string;
  severity: "low" | "medium" | "high";
  excerpt: string;
  explanation: string;
  recommendation: string;
}

export interface Analysis {
  metrics: {
    words: number;
    characters: number;
    sentences: number;
    paragraphs: number;
    words_per_minute: number;
    estimated_minutes: number;
    target_min: number;
    target_max: number;
    within_target: boolean;
    avg_sentence_words: number;
    long_sentences: number;
    repeated_sentences: { text: string; count: number }[];
    repeated_phrases: { text: string; count: number }[];
  };
  ai: {
    summary: string;
    verdict: "approved" | "needs_revision" | "high_risk";
    scores: Record<string, number | null>;
    hook_assessment: string;
    structure: { title: string; starts_with: string; assessment: string }[];
    ending_assessment: string;
    pacing_assessment: string;
    issues: Issue[];
    repetition_notes: string[];
    policy_risks: PolicyRisk[];
    originality_assessment: string;
    channel_fit_assessment: string;
    improvements: string[];
  };
  model: string;
  created_at: string;
}

export interface Concept {
  id: number;
  position: number;
  name: string;
  idea: string;
  emotion: string;
  composition: string;
  overlay_text: string;
  prompt: string;
  rationale: string;
  selected_asset_id: number | null;
  images: Asset[];
  created_at: string;
}

export interface MetadataSuggestions {
  titles: { title: string; angle: string }[];
  description: string;
  description_body: string;
  chapters: { seconds: number; time: string; title: string; scene: number }[];
  tags: string[];
  hashtags: string[];
  primary_keywords: string[];
  secondary_keywords: string[];
  policy_notes: string[];
  model: string;
  timeline_source: "audio" | "estimate";
}

export interface Totals {
  cost: number;
  tokens_in: number;
  tokens_out: number;
  tokens: number;
  calls: number;
  pending: number;
}

export interface StageCost extends Totals {
  stage: string;
  label: string;
}

export interface ProjectSummary {
  id: number;
  channel_id: number;
  title: string;
  status: string;
  quality: Quality;
  selected_title: string;
  words: number;
  scenes: number | null;
  cost: number;
  archived: boolean;
  created_at: string;
  updated_at: string;
  channel_name?: string | null;
}

export interface Stages {
  script: { words: number; ready: boolean; analyzed: boolean; analysis_fresh: boolean; verdict: string | null };
  scenes: { count: number; fresh: boolean; video: number; duration: number };
  visuals: { ready: number; total: number };
  narration: { ready: number; total: number; duration: number; full: Asset | null };
  thumbnail: { concepts: number; images: number; selected: boolean };
  metadata: { ready: boolean; title: string };
  export: { count: number; last: Asset | null; outdated: boolean };
}

export interface ProjectDetail extends ProjectSummary {
  script: string;
  notes: string;
  target_minutes: number | null;
  analysis: Analysis | null;
  plan: ProductionPlan | null;
  analysis_at: string | null;
  metadata_suggestions: MetadataSuggestions | null;
  description: string;
  tags: string[];
  channel: Channel;
  scenes_list: Scene[];
  concepts: Concept[];
  stages: Stages;
  tts: { model: string; voice: string | null; speed: number; style: string; warning: string } | null;
  active_jobs: Job[];
  costs: Totals;
}

export interface EstimateLine {
  key: string;
  stage: string;
  label: string;
  model: string | null;
  quantity: number;
  unit: string;
  cost: number | null;
  source: "live" | "history" | "heuristic" | "free" | "unavailable";
  note: string;
  tokens_in: number | null;
  tokens_out: number | null;
}

export interface Estimate {
  inputs: {
    words: number;
    chars: number;
    minutes: number;
    scenes: number;
    seconds: number;
    from_target: boolean;
    scenes_planned: boolean;
    language: string;
  };
  tiers: Record<Quality, TierEstimate>;
  current: Quality;
  fx: Fx;
  catalog_at: string;
}

export interface ProductionPlan {
  tier: Quality;
  scene_seconds: number | null;
  video_share: number | null;
  scenes: number;
  image_model: string | null;
  image_resolution: string | null;
  cap_brl: number | null;
  total_usd: number;
  total_brl: number;
  fits: boolean | null;
  adjustments: string[];
}

export interface TierEstimate {
  scenes: number;
  total: number;
  total_brl: number;
  complete: boolean;
  missing: string[];
  lines: EstimateLine[];
  models: Record<string, string | null>;
  cap_brl: number | null;
  cap_usd: number | null;
  fits: boolean | null;
  adjustments: string[];
  plan: ProductionPlan;
}

export interface Fx {
  rate: number;
  source: "manual" | "live" | "last" | "default";
  at: string | null;
  note: string;
}

export interface Skill {
  id: number;
  version: number;
  content: string;
  note: string;
  source: string;
  created_at: string;
}

export interface Learning {
  id: number;
  channel_id: number;
  project_id: number | null;
  category: string;
  text: string;
  rationale: string;
  status: "proposed" | "accepted" | "rejected" | "merged";
  source: string;
  created_at: string;
  decided_at: string | null;
}

export interface Balance {
  available: boolean;
  balance: number | null;
  source: "credits" | "key_limit" | null;
  reason?: string;
  key: Record<string, unknown> | null;
  credits: { total_credits: number; total_usage: number } | null;
  key_error?: string;
  credits_error?: string;
}

export interface UsageSummary {
  total: Totals;
  today: Totals;
  last_7_days: Totals;
  month: Totals;
  stages: StageCost[];
  models: (Totals & { model: string; operation: string })[];
  channels: (Totals & { channel_id: number | null; name: string })[];
  projects: (Totals & { project_id: number; title: string; channel_id: number | null })[];
  days: { day: string; cost: number }[];
  budget: Budget;
}

export interface Budget {
  daily_limit_usd: number | null;
  project_limit_usd: number | null;
}

export interface Resolved {
  model: string | null;
  source: "config" | "preferred" | "auto" | "missing";
  note: string;
}

export interface TierConfig {
  text: string | null;
  image: string | null;
  thumbnail: string | null;
  tts: string | null;
  video: string | null;
  image_resolution: string;
  video_resolution: string;
  thumb_concepts: number;
  thumb_variations: number;
  video_share: number;
  reasoning: string | null;
  min_scene_seconds: number;
  cap_brl: number;
}

export interface SettingsData {
  tiers: Record<Quality, TierConfig>;
  resolved: Record<Quality, Record<string, Resolved>>;
  operations: Record<string, string>;
  budget: Budget;
  fx: Fx;
  providers: { openrouter: { configured: boolean; base_url: string; management_key: boolean } };
  catalog: Record<string, { count: number; fetched_at: string | null }>;
  app: { env: string; public_url: string; embedded_worker: boolean; lanes: Record<string, number>; catalog_ttl_minutes: number };
}

export interface CatalogModel {
  id: string;
  name: string;
  created: number | null;
  context_length?: number | null;
  prompt_per_m?: number | null;
  completion_per_m?: number | null;
  structured?: boolean;
  voices?: string[];
  per_char?: boolean;
  image_api?: boolean;
  per_image?: number | null;
  price_source?: string;
  per_second_720p?: number | null;
  price_note?: string;
  durations?: number[] | null;
  resolutions?: string[] | null;
}

export interface Dashboard {
  counts: { channels: number; projects: number; projects_by_status: Record<string, number> };
  queue: { queued: number; running: number };
  costs: { today: Totals; month: Totals; total: Totals };
  budget: Budget;
  recent_projects: ProjectSummary[];
  active_jobs: Job[];
  recent_failures: Job[];
  workers: { id: string; host: string; seen_at: string }[];
  openrouter_configured: boolean;
}

export interface SystemStatus {
  version: string;
  env: string;
  workers: { id: string; host: string; seen_at: string; info: Record<string, unknown> }[];
  queue: Record<string, number>;
  openrouter_configured: boolean;
  management_key_configured: boolean;
  embedded_worker: boolean;
  database: string;
}
