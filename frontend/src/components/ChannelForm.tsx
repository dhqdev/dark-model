import { useQuery } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { api, errorMessage, postForBlob } from "../lib/api";
import { LANGUAGES, usd } from "../lib/format";
import type { CatalogModel, Channel, Quality } from "../lib/types";
import { Btn, ErrorBox, Field, Segmented, useToast } from "./ui";

export type ChannelDraft = Omit<Channel, "id" | "slug" | "stats" | "created_at" | "updated_at" | "archived" | "default_wpm"> & { skill?: string };

export const EMPTY_CHANNEL: ChannelDraft = {
  name: "",
  language: "en-US",
  country: "",
  audience: "",
  niche: "",
  style: "",
  tone: "",
  duration_min: 15,
  duration_max: 25,
  words_per_minute: null,
  scene_seconds: 7,
  visual_style: "",
  default_quality: "BALANCED",
  tts_model: null,
  tts_voice: null,
  tts_speed: 1,
  tts_style: "",
  thumbnail_style: "",
  thumbnail_text_mode: "in_image",
  auto_learn: true,
  notes: "",
  skill: "",
};

function Section({ n, title, children }: { n: string; title: string; children: React.ReactNode }) {
  return (
    <fieldset className="border-t border-line pt-4">
      <legend className="mb-3 pr-3 font-mono text-[10.5px] tracking-[0.18em] text-paper uppercase">
        <span className="mr-2 text-amber">{n}</span>
        {title}
      </legend>
      <div className="grid gap-4 md:grid-cols-2">{children}</div>
    </fieldset>
  );
}

export function ChannelForm({
  initial,
  channelId,
  onSubmit,
  submitLabel,
  busy,
  error,
}: {
  initial: ChannelDraft;
  channelId?: number;
  onSubmit: (draft: ChannelDraft) => void;
  submitLabel: string;
  busy?: boolean;
  error?: unknown;
}) {
  const [d, setD] = useState<ChannelDraft>(initial);
  const [previewing, setPreviewing] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [previewCost, setPreviewCost] = useState<string>("");
  const toast = useToast();
  const set = <K extends keyof ChannelDraft>(k: K, v: ChannelDraft[K]) => setD((x) => ({ ...x, [k]: v }));

  const speech = useQuery({ queryKey: ["catalog", "speech"], queryFn: () => api.get<CatalogModel[]>("/catalog/speech"), staleTime: 300_000 });
  const voices = useMemo(() => speech.data?.find((m) => m.id === d.tts_model)?.voices ?? [], [speech.data, d.tts_model]);
  const effective = useQuery({
    queryKey: ["voices", channelId, d.tts_model],
    queryFn: () => api.get<{ model: string | null; voices: string[] }>(`/channels/${channelId}/voices${d.tts_model ? `?model=${encodeURIComponent(d.tts_model)}` : ""}`),
    enabled: !!channelId,
  });
  const voiceOptions = d.tts_model ? voices : (effective.data?.voices ?? []);

  async function preview() {
    if (!channelId) return;
    setPreviewing(true);
    try {
      const { blob, headers } = await postForBlob(`/channels/${channelId}/voice-preview`, {
        model: d.tts_model || null,
        voice: d.tts_voice || null,
        speed: d.tts_speed,
      });
      setAudioUrl((old) => {
        if (old) URL.revokeObjectURL(old);
        return URL.createObjectURL(blob);
      });
      const cost = headers.get("X-Cost-USD");
      setPreviewCost(cost ? `custo real ${usd(Number(cost), 5)}` : "custo será confirmado pela OpenRouter");
    } catch (e) {
      toast(errorMessage(e), "err");
    } finally {
      setPreviewing(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    onSubmit(d);
  }

  return (
    <form onSubmit={submit} className="space-y-6">
      <Section n="01" title="Identidade">
        <Field label="Nome do canal">
          <input className="input" value={d.name} onChange={(e) => set("name", e.target.value)} required maxLength={160} />
        </Field>
        <div className="grid grid-cols-[1fr_110px] gap-3">
          <Field label="Idioma de produção">
            <select className="input" value={d.language} onChange={(e) => set("language", e.target.value)}>
              {LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.label} · {l.code}
                </option>
              ))}
            </select>
          </Field>
          <Field label="País">
            <input className="input uppercase" value={d.country} onChange={(e) => set("country", e.target.value.toUpperCase())} maxLength={8} placeholder="PL" />
          </Field>
        </div>
        <Field label="Nicho">
          <input className="input" value={d.niche} onChange={(e) => set("niche", e.target.value)} placeholder="Mistérios históricos, true crime, espaço…" />
        </Field>
        <Field label="Público">
          <input className="input" value={d.audience} onChange={(e) => set("audience", e.target.value)} placeholder="Adultos 25–45 que gostam de documentários" />
        </Field>
      </Section>

      <Section n="02" title="Estilo e tom">
        <Field label="Estilo narrativo">
          <input className="input" value={d.style} onChange={(e) => set("style", e.target.value)} placeholder="Documentário investigativo, narrativa em atos" />
        </Field>
        <Field label="Tom">
          <input className="input" value={d.tone} onChange={(e) => set("tone", e.target.value)} placeholder="Sombrio, calmo, misterioso" />
        </Field>
        <Field label="Estilo visual (vai em todos os prompts)" className="md:col-span-2">
          <textarea className="input" rows={2} value={d.visual_style} onChange={(e) => set("visual_style", e.target.value)} placeholder="cinematic, low-key lighting, muted earth tones, 35mm film grain" />
        </Field>
        <Field label="Estilo das thumbnails">
          <input className="input" value={d.thumbnail_style} onChange={(e) => set("thumbnail_style", e.target.value)} placeholder="alto contraste, vermelho e preto" />
        </Field>
        <Field label="Texto na thumbnail">
          <Segmented
            value={d.thumbnail_text_mode}
            onChange={(v) => set("thumbnail_text_mode", v)}
            options={[
              { value: "in_image", label: "Gerado na imagem" },
              { value: "none", label: "Sem texto (edito depois)" },
            ]}
          />
        </Field>
      </Section>

      <Section n="03" title="Produção">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Duração mín. (min)">
            <input className="input tnum" type="number" min={1} max={180} value={d.duration_min} onChange={(e) => set("duration_min", Number(e.target.value))} />
          </Field>
          <Field label="Duração máx. (min)">
            <input className="input tnum" type="number" min={1} max={240} value={d.duration_max} onChange={(e) => set("duration_max", Number(e.target.value))} />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Palavras/min" hint="vazio = padrão do idioma">
            <input
              className="input tnum"
              type="number"
              min={60}
              max={400}
              value={d.words_per_minute ?? ""}
              onChange={(e) => set("words_per_minute", e.target.value ? Number(e.target.value) : null)}
            />
          </Field>
          <Field label="Segundos por cena" hint="média alvo">
            <input className="input tnum" type="number" min={2} max={30} step={0.5} value={d.scene_seconds} onChange={(e) => set("scene_seconds", Number(e.target.value))} />
          </Field>
        </div>
        <Field label="Qualidade padrão dos projetos">
          <Segmented<Quality>
            value={d.default_quality}
            onChange={(v) => set("default_quality", v)}
            options={[
              { value: "ECONOMY", label: "Economy" },
              { value: "BALANCED", label: "Balanced" },
              { value: "PREMIUM", label: "Premium" },
            ]}
          />
        </Field>
        <label className="flex items-center gap-3 self-end text-[13px] text-muted">
          <input type="checkbox" className="accent-amber" checked={d.auto_learn} onChange={(e) => set("auto_learn", e.target.checked)} />
          Propor aprendizados para a Skill ao exportar cada projeto
        </label>
      </Section>

      <Section n="04" title="Narração">
        <Field label="Modelo de voz (TTS)" hint="vazio = definido pelo nível de qualidade">
          <select className="input" value={d.tts_model ?? ""} onChange={(e) => setD((x) => ({ ...x, tts_model: e.target.value || null, tts_voice: null }))}>
            <option value="">Automático pelo nível</option>
            {(speech.data ?? []).map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} — {m.per_char ? `$${m.prompt_per_m}/1M caract.` : `$${m.prompt_per_m}/$${m.completion_per_m} por 1M tokens`}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Voz" hint={!voiceOptions.length ? "carregue o catálogo em Configurações" : `${voiceOptions.length} vozes disponíveis`}>
          <select className="input" value={d.tts_voice ?? ""} onChange={(e) => set("tts_voice", e.target.value || null)}>
            <option value="">Primeira disponível</option>
            {voiceOptions.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </Field>
        <Field label={`Velocidade · ${d.tts_speed.toFixed(2)}×`}>
          <input type="range" min={0.7} max={1.3} step={0.05} value={d.tts_speed} onChange={(e) => set("tts_speed", Number(e.target.value))} className="w-full accent-amber" />
        </Field>
        <Field label="Estilo de leitura" hint="instruções de interpretação (aplicadas em modelos OpenAI)">
          <input className="input" value={d.tts_style} onChange={(e) => set("tts_style", e.target.value)} placeholder="Voz grave, ritmo pausado, suspense" />
        </Field>
        {channelId && (
          <div className="flex flex-wrap items-center gap-3 md:col-span-2">
            <Btn size="sm" icon={<Play size={11} />} onClick={() => void preview()} loading={previewing}>
              Testar voz
            </Btn>
            {audioUrl && <audio src={audioUrl} controls autoPlay className="h-8" />}
            {previewCost && <span className="font-mono text-[11px] text-dim">{previewCost}</span>}
          </div>
        )}
      </Section>

      {d.skill !== undefined && (
        <fieldset className="border-t border-line pt-4">
          <legend className="mb-3 pr-3 font-mono text-[10.5px] tracking-[0.18em] text-paper uppercase">
            <span className="mr-2 text-amber">05</span>Skill inicial (opcional)
          </legend>
          <textarea
            className="input font-mono text-[12.5px]"
            rows={5}
            value={d.skill}
            onChange={(e) => set("skill", e.target.value)}
            placeholder="Deixe vazio para começar com o modelo padrão. Depois você pode editar ou gerar a Skill com IA."
          />
        </fieldset>
      )}

      <Field label="Notas internas">
        <textarea className="input" rows={2} value={d.notes} onChange={(e) => set("notes", e.target.value)} />
      </Field>

      {error ? <ErrorBox error={error} /> : null}
      <div className="flex justify-end">
        <Btn type="submit" variant="primary" loading={busy}>
          {submitLabel}
        </Btn>
      </div>
    </form>
  );
}
