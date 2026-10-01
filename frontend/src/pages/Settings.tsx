import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { PlugZap, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Badge, Btn, ErrorBox, Field, Loading, Modal, Notice, PageHeader, Panel, useToast } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { dateTime, QUALITY_LABEL, usd } from "../lib/format";
import type { Budget, CatalogModel, Quality, SettingsData, SystemStatus, TierConfig } from "../lib/types";

const TIERS: Quality[] = ["ECONOMY", "BALANCED", "PREMIUM"];
const OPS = ["text", "image", "thumbnail", "tts", "video"] as const;
type Op = (typeof OPS)[number];
const OP_KIND: Record<Op, string> = { text: "text", image: "image", thumbnail: "image", tts: "speech", video: "video" };
const SOURCE: Record<string, { label: string; tone: "amber" | "ok" | "info" | "err" }> = {
  config: { label: "fixado", tone: "amber" },
  preferred: { label: "preferido", tone: "ok" },
  auto: { label: "auto", tone: "info" },
  missing: { label: "ausente", tone: "err" },
};

function priceOf(m: CatalogModel, kind: string): string {
  if (kind === "video") return m.per_second_720p != null ? `${usd(m.per_second_720p)}/s (720p)` : "preço por SKU";
  if (kind === "speech") return m.per_char ? `$${m.prompt_per_m}/1M caract.` : `$${m.prompt_per_m} · $${m.completion_per_m} /1M tok`;
  if (kind === "image") return m.image_api ? "API de imagens" : `via chat · $${m.completion_per_m}/1M tok`;
  return m.prompt_per_m != null ? `$${m.prompt_per_m} in · $${m.completion_per_m} out /1M` : "—";
}

function ModelPicker({ op, tier, current, onPick, onClose }: { op: Op; tier: Quality; current: string | null; onPick: (id: string | null) => void; onClose: () => void }) {
  const kind = OP_KIND[op];
  const [q, setQ] = useState("");
  const { data, isLoading } = useQuery({ queryKey: ["catalog", kind], queryFn: () => api.get<CatalogModel[]>(`/catalog/${kind}`), staleTime: 300_000 });
  const list = useMemo(() => (data ?? []).filter((m) => !q || m.id.toLowerCase().includes(q.toLowerCase()) || m.name.toLowerCase().includes(q.toLowerCase())), [data, q]);
  return (
    <Modal open onClose={onClose} title={`${QUALITY_LABEL[tier]} · ${op}`} wide>
      <div className="mb-3 flex gap-2">
        <input className="input" placeholder="Buscar modelo…" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
        <Btn onClick={() => onPick(null)}>Automático</Btn>
      </div>
      {isLoading && <Loading />}
      {!isLoading && !data?.length && <Notice tone="amber">Catálogo vazio. Verifique a chave e clique em “Atualizar catálogo”.</Notice>}
      <div className="max-h-[60vh] overflow-y-auto border border-line">
        {list.map((m) => (
          <button
            key={m.id}
            onClick={() => onPick(m.id)}
            className={clsx("grid w-full grid-cols-[1fr_auto] gap-4 border-b border-line px-3 py-2 text-left last:border-b-0 hover:bg-raised", m.id === current && "bg-amber/10")}
          >
            <span className="min-w-0">
              <span className="block truncate font-mono text-[12.5px] text-paper">{m.id}</span>
              <span className="block truncate text-[12px] text-dim">
                {m.name}
                {m.voices?.length ? ` · ${m.voices.length} vozes` : ""}
                {m.durations?.length ? ` · ${m.durations.join("/")}s` : ""}
                {m.structured === false ? " · sem JSON estruturado" : ""}
              </span>
            </span>
            <span className="tnum self-center font-mono text-[11px] text-muted">{priceOf(m, kind)}</span>
          </button>
        ))}
      </div>
    </Modal>
  );
}

export function Settings() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data, isLoading, error } = useQuery({ queryKey: ["settings"], queryFn: () => api.get<SettingsData>("/settings") });
  const system = useQuery({ queryKey: ["system"], queryFn: () => api.get<SystemStatus>("/system/status") });
  const [tiers, setTiers] = useState<Record<Quality, TierConfig> | null>(null);
  const [budget, setBudget] = useState<Budget>({ daily_limit_usd: null, project_limit_usd: null });
  const [picker, setPicker] = useState<{ op: Op; tier: Quality } | null>(null);
  useEffect(() => {
    if (data) {
      setTiers(data.tiers);
      setBudget(data.budget);
    }
  }, [data]);

  const saveTiers = useMutation({
    mutationFn: () => api.put("/settings/tiers", { tiers }),
    onSuccess: () => {
      toast("Níveis de qualidade salvos");
      void qc.invalidateQueries({ queryKey: ["settings"] });
      void qc.invalidateQueries({ queryKey: ["estimate"] });
    },
    onError: (e) => toast(errorMessage(e), "err"),
  });
  const saveBudget = useMutation({
    mutationFn: () => api.put("/settings/budget", budget),
    onSuccess: () => {
      toast("Limites de gasto salvos");
      void qc.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (e) => toast(errorMessage(e), "err"),
  });
  const refreshCatalog = useMutation({
    mutationFn: () => api.post<Record<string, { ok: boolean; count?: number; error?: string }>>("/catalog/refresh"),
    onSuccess: (r) => {
      const bad = Object.entries(r).filter(([, v]) => !v.ok);
      toast(bad.length ? `Catálogo com falhas: ${bad.map(([k, v]) => `${k}: ${v.error}`).join("; ")}` : "Catálogo atualizado", bad.length ? "err" : "ok");
      void qc.invalidateQueries({ queryKey: ["settings"] });
      void qc.invalidateQueries({ queryKey: ["catalog"] });
    },
    onError: (e) => toast(errorMessage(e), "err"),
  });
  const test = useMutation({
    mutationFn: () => api.post<{ ok: boolean; label: string; is_free_tier: boolean }>("/settings/test-openrouter"),
    onSuccess: (r) => toast(`Conexão OK · chave “${r.label}”${r.is_free_tier ? " (free tier)" : ""}`),
    onError: (e) => toast(errorMessage(e), "err"),
  });

  if (isLoading || !tiers) return <Loading />;
  if (error || !data) return <ErrorBox error={error} />;
  const dirty = JSON.stringify(tiers) !== JSON.stringify(data.tiers);
  const setParam = (tier: Quality, key: keyof TierConfig, value: unknown) => setTiers((t) => (t ? { ...t, [tier]: { ...t[tier], [key]: value } } : t));

  return (
    <div>
      <PageHeader kicker="05 / Configurações" title="Configurações" subtitle="Modelos por nível de qualidade, limites de gasto e conexão com a OpenRouter. As chaves ficam só no servidor (Stack do Portainer)." />
      <div className="grid items-start gap-6 2xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-6">
          <Panel
            index="01"
            title="Níveis de qualidade"
            actions={
              <Btn variant="primary" size="sm" disabled={!dirty} loading={saveTiers.isPending} onClick={() => saveTiers.mutate()}>
                Salvar níveis
              </Btn>
            }
          >
            <p className="mb-4 text-[12.5px] text-muted">
              Sem um modelo fixado, o sistema escolhe no catálogo real da OpenRouter a versão mais nova da família preferida (ex.: Claude Sonnet no Balanced) ou, se ela não
              existir, pela faixa de preço. Clique num modelo para fixar outro.
            </p>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] border-collapse text-[13px]">
                <thead>
                  <tr className="border-b border-edge">
                    <th className="kicker w-48 py-2 pr-3 text-left font-normal">Operação</th>
                    {TIERS.map((t) => (
                      <th key={t} className="kicker py-2 pl-3 text-left font-normal">
                        {QUALITY_LABEL[t]}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {OPS.map((op) => (
                    <tr key={op} className="border-b border-line align-top">
                      <td className="py-2.5 pr-3 text-muted">{data.operations[op]}</td>
                      {TIERS.map((t) => {
                        const pinned = tiers[t][op];
                        const resolved = data.resolved[t][op];
                        const shown = pinned ?? resolved.model;
                        const src = pinned && pinned !== data.tiers[t][op] ? { label: "não salvo", tone: "amber" as const } : SOURCE[pinned ? "config" : resolved.source];
                        return (
                          <td key={t} className="py-2 pl-3">
                            <button className="w-full border border-transparent px-2 py-1.5 text-left hover:border-edge" onClick={() => setPicker({ op, tier: t })} title={resolved.note}>
                              <span className="block truncate font-mono text-[12px] text-paper">{shown ?? "—"}</span>
                              <Badge tone={src.tone} className="mt-1">
                                {src.label}
                              </Badge>
                            </button>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                  <tr className="border-b border-line">
                    <td className="py-2.5 pr-3 text-muted">Resolução das imagens</td>
                    {TIERS.map((t) => (
                      <td key={t} className="py-2 pl-3">
                        <select className="input py-1.5" value={tiers[t].image_resolution} onChange={(e) => setParam(t, "image_resolution", e.target.value)}>
                          {["1K", "2K", "4K"].map((r) => (
                            <option key={r}>{r}</option>
                          ))}
                        </select>
                      </td>
                    ))}
                  </tr>
                  <tr className="border-b border-line">
                    <td className="py-2.5 pr-3 text-muted">Resolução dos vídeos IA</td>
                    {TIERS.map((t) => (
                      <td key={t} className="py-2 pl-3">
                        <select className="input py-1.5" value={tiers[t].video_resolution} onChange={(e) => setParam(t, "video_resolution", e.target.value)}>
                          {["480p", "720p", "1080p"].map((r) => (
                            <option key={r}>{r}</option>
                          ))}
                        </select>
                      </td>
                    ))}
                  </tr>
                  <tr className="border-b border-line">
                    <td className="py-2.5 pr-3 text-muted">Cenas com vídeo IA (máx. %)</td>
                    {TIERS.map((t) => (
                      <td key={t} className="py-2 pl-3">
                        <input className="input tnum py-1.5" type="number" min={0} max={100} value={Math.round(tiers[t].video_share * 100)} onChange={(e) => setParam(t, "video_share", Number(e.target.value) / 100)} />
                      </td>
                    ))}
                  </tr>
                  <tr className="border-b border-line">
                    <td className="py-2.5 pr-3 text-muted">Thumbnails (conceitos × variações)</td>
                    {TIERS.map((t) => (
                      <td key={t} className="py-2 pl-3">
                        <div className="flex items-center gap-1.5">
                          <input className="input tnum py-1.5" type="number" min={1} max={8} value={tiers[t].thumb_concepts} onChange={(e) => setParam(t, "thumb_concepts", Number(e.target.value))} />
                          <span className="text-dim">×</span>
                          <input className="input tnum py-1.5" type="number" min={1} max={4} value={tiers[t].thumb_variations} onChange={(e) => setParam(t, "thumb_variations", Number(e.target.value))} />
                        </div>
                      </td>
                    ))}
                  </tr>
                  <tr>
                    <td className="py-2.5 pr-3 text-muted">Raciocínio (modelos que suportam)</td>
                    {TIERS.map((t) => (
                      <td key={t} className="py-2 pl-3">
                        <select className="input py-1.5" value={tiers[t].reasoning ?? ""} onChange={(e) => setParam(t, "reasoning", e.target.value || null)}>
                          <option value="">padrão do modelo</option>
                          {["low", "medium", "high"].map((r) => (
                            <option key={r}>{r}</option>
                          ))}
                        </select>
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel index="02" title="Limites de gasto">
            <p className="mb-4 text-[12.5px] text-muted">Ao atingir um limite, novas gerações pagas param com aviso (renderização local e exportação continuam). Vazio = sem limite.</p>
            <div className="grid gap-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
              <Field label="Limite diário (US$)">
                <input className="input tnum" type="number" min={0} step={0.5} value={budget.daily_limit_usd ?? ""} onChange={(e) => setBudget({ ...budget, daily_limit_usd: e.target.value ? Number(e.target.value) : null })} />
              </Field>
              <Field label="Limite por projeto (US$)">
                <input className="input tnum" type="number" min={0} step={0.5} value={budget.project_limit_usd ?? ""} onChange={(e) => setBudget({ ...budget, project_limit_usd: e.target.value ? Number(e.target.value) : null })} />
              </Field>
              <Btn variant="primary" loading={saveBudget.isPending} onClick={() => saveBudget.mutate()}>
                Salvar limites
              </Btn>
            </div>
          </Panel>
        </div>

        <div className="grid min-w-0 gap-6 md:grid-cols-2 2xl:grid-cols-1">
          <Panel index="03" title="OpenRouter">
            <div className="space-y-2.5 font-mono text-[12px]">
              <div className="flex justify-between">
                <span className="text-muted">OPENROUTER_API_KEY</span>
                {data.providers.openrouter.configured ? <Badge tone="ok">configurada</Badge> : <Badge tone="err">ausente</Badge>}
              </div>
              <div className="flex justify-between">
                <span className="text-muted">Chave de gerenciamento</span>
                {data.providers.openrouter.management_key ? <Badge tone="ok">sim</Badge> : <Badge tone="dim">não (saldo limitado)</Badge>}
              </div>
              <div className="flex justify-between gap-3">
                <span className="text-muted">Endpoint</span>
                <span className="truncate text-paper">{data.providers.openrouter.base_url}</span>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <Btn size="sm" icon={<PlugZap size={11} />} loading={test.isPending} onClick={() => test.mutate()} disabled={!data.providers.openrouter.configured}>
                Testar conexão
              </Btn>
              <Btn size="sm" icon={<RefreshCw size={11} />} loading={refreshCatalog.isPending} onClick={() => refreshCatalog.mutate()} disabled={!data.providers.openrouter.configured}>
                Atualizar catálogo
              </Btn>
            </div>
            <div className="mt-4 border-t border-line pt-3">
              <div className="kicker mb-2">Catálogo (modelos e preços)</div>
              {Object.entries(data.catalog).map(([k, v]) => (
                <div key={k} className="flex justify-between py-0.5 font-mono text-[11.5px]">
                  <span className="text-muted">{k}</span>
                  <span className="text-paper">
                    {v.count} · <span className="text-dim">{dateTime(v.fetched_at)}</span>
                  </span>
                </div>
              ))}
            </div>
          </Panel>
          <Panel index="04" title="Sistema">
            <div className="space-y-1.5 font-mono text-[11.5px]">
              {(
                [
                  ["Versão", system.data?.version],
                  ["Ambiente", data.app.env],
                  ["Banco", system.data?.database],
                  ["Worker embutido", data.app.embedded_worker ? "sim" : "não"],
                  ["Vagas", Object.entries(data.app.lanes).map(([k, v]) => `${k}=${v}`).join(" ")],
                  ["Cache do catálogo", `${data.app.catalog_ttl_minutes} min`],
                ] as [string, string | undefined][]
              ).map(([k, v]) => (
                <div key={k} className="flex justify-between gap-3">
                  <span className="text-muted">{k}</span>
                  <span className="truncate text-paper">{v ?? "—"}</span>
                </div>
              ))}
              <div className="pt-2">
                <div className="kicker mb-1">Workers online</div>
                {(system.data?.workers ?? []).length === 0 && <div className="text-signal">nenhum</div>}
                {(system.data?.workers ?? []).map((w) => (
                  <div key={w.id} className="flex items-center gap-2 text-paper">
                    <span className="led led-ok" /> {w.id}
                  </div>
                ))}
              </div>
            </div>
          </Panel>
        </div>
      </div>
      {picker && (
        <ModelPicker
          op={picker.op}
          tier={picker.tier}
          current={tiers[picker.tier][picker.op]}
          onClose={() => setPicker(null)}
          onPick={(id) => {
            setParam(picker.tier, picker.op, id);
            setPicker(null);
          }}
        />
      )}
    </div>
  );
}
