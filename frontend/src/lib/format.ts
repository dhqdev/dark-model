export function usd(value: number | null | undefined, digits?: number): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (value === 0) return "$0.00";
  const d = digits ?? (Math.abs(value) >= 100 ? 2 : Math.abs(value) >= 1 ? 2 : Math.abs(value) >= 0.01 ? 3 : 4);
  return `$${value.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })}`;
}

export function brl(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function num(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function tokens(value: number | null | undefined): string {
  if (!value) return "0";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 10_000) return `${(value / 1000).toFixed(1)}k`;
  return value.toLocaleString("pt-BR");
}

export function timecode(seconds: number | null | undefined, frames = false): string {
  const s = Math.max(0, seconds ?? 0);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  const base = `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  if (!frames) return base;
  const f = Math.floor((s % 1) * 30);
  return `${base}:${String(f).padStart(2, "0")}`;
}

export function secs(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(1)}s`;
}

export function minutes(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}min${s ? ` ${s}s` : ""}`;
}

export function bytes(n: number | null | undefined): string {
  if (!n) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function relative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 45) return "agora";
  if (diff < 3600) return `há ${Math.round(diff / 60)} min`;
  if (diff < 86400) return `há ${Math.round(diff / 3600)} h`;
  return `há ${Math.round(diff / 86400)} d`;
}

export const QUALITY_LABEL: Record<string, string> = {
  ECONOMY: "Economy",
  BALANCED: "Balanced",
  PREMIUM: "Premium",
};

export const ASSET_TYPE_LABEL: Record<string, string> = {
  IMAGE: "Imagem",
  IMAGE_MOTION: "Imagem + Motion",
  VIDEO: "Vídeo",
};

export const MOTION_LABEL: Record<string, string> = {
  zoom_in: "Zoom in",
  zoom_out: "Zoom out",
  pan_left: "Pan ←",
  pan_right: "Pan →",
  pan_up: "Pan ↑",
  pan_down: "Pan ↓",
  static: "Estático",
};

export const TRANSITION_LABEL: Record<string, string> = {
  dissolve: "Dissolver",
  fadeblack: "Fade preto",
  flash: "Flash",
  slide: "Deslizar",
  zoom: "Zoom",
  blur: "Desfoque",
  circle: "Círculo",
  cut: "Corte seco",
};

export const SFX_LABEL: Record<string, string> = {
  none: "Nenhum",
  whoosh: "Whoosh",
  impact: "Impacto",
  riser: "Subida (riser)",
  tension: "Tensão",
  heartbeat: "Batimento",
  wind: "Vento",
  rumble: "Estrondo grave",
  clock: "Relógio",
};

export const STATUS_LABEL: Record<string, string> = {
  queued: "Na fila",
  running: "Rodando",
  succeeded: "Concluído",
  failed: "Falhou",
  canceled: "Cancelado",
};

export const PROJECT_STATUS: Record<string, string> = {
  draft: "Rascunho",
  script: "Roteiro",
  scenes: "Cenas",
  production: "Produção",
  ready: "Pronto",
  exported: "Exportado",
};

export const SOURCE_LABEL: Record<string, string> = {
  live: "Preço do catálogo OpenRouter",
  history: "Média dos seus custos reais",
  heuristic: "Preço real, quantidade aproximada",
  free: "Sem custo (local)",
  unavailable: "Sem preço publicado — custo real após gerar",
};

export const LANGUAGES: { code: string; label: string }[] = [
  { code: "en-US", label: "Inglês (EUA)" },
  { code: "en-GB", label: "Inglês (Reino Unido)" },
  { code: "pt-BR", label: "Português (Brasil)" },
  { code: "pt-PT", label: "Português (Portugal)" },
  { code: "es-ES", label: "Espanhol (Espanha)" },
  { code: "es-MX", label: "Espanhol (México)" },
  { code: "de-DE", label: "Alemão" },
  { code: "pl-PL", label: "Polonês" },
  { code: "fr-FR", label: "Francês" },
  { code: "it-IT", label: "Italiano" },
  { code: "nl-NL", label: "Holandês" },
  { code: "sv-SE", label: "Sueco" },
  { code: "ro-RO", label: "Romeno" },
  { code: "cs-CZ", label: "Tcheco" },
  { code: "tr-TR", label: "Turco" },
  { code: "ru-RU", label: "Russo" },
  { code: "uk-UA", label: "Ucraniano" },
  { code: "ja-JP", label: "Japonês" },
  { code: "ko-KR", label: "Coreano" },
  { code: "hi-IN", label: "Hindi" },
  { code: "ar-SA", label: "Árabe" },
  { code: "id-ID", label: "Indonésio" },
];
