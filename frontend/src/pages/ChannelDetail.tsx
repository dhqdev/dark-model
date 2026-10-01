import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Check, Plus, RotateCcw, Sparkles, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ChannelForm, type ChannelDraft } from "../components/ChannelForm";
import { JobLine } from "../components/jobs";
import { Badge, Btn, Empty, ErrorBox, Field, LineDiff, Loading, MarkdownView, Modal, Notice, PageHeader, Panel, Segmented, useToast } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { bytes, dateTime, PROJECT_STATUS, QUALITY_LABEL, relative, usd } from "../lib/format";
import type { Channel, Job, Learning, ProjectSummary, Quality, Skill } from "../lib/types";

type Tab = "projects" | "skill" | "learnings" | "settings";

export function ChannelDetail() {
  const { channelId } = useParams();
  const id = Number(channelId);
  const [tab, setTab] = useState<Tab>("projects");
  const { data: channel, isLoading, error } = useQuery({ queryKey: ["channel", id], queryFn: () => api.get<Channel>(`/channels/${id}`) });
  const jobs = useQuery({
    queryKey: ["jobs", "channel", id],
    queryFn: () => api.get<{ jobs: Job[] }>(`/jobs?channel_id=${id}&status=active`),
    refetchInterval: (q) => ((q.state.data?.jobs.length ?? 0) > 0 ? 2500 : 15000),
  });

  if (isLoading) return <Loading />;
  if (error || !channel) return <ErrorBox error={error} />;
  const pending = channel.stats.pending_learnings ?? 0;

  return (
    <div>
      <PageHeader
        kicker={`02 / Canais / ${channel.language}`}
        title={channel.name}
        subtitle={[channel.niche, channel.audience].filter(Boolean).join(" · ") || "Configure nicho e público na aba Configurações."}
        actions={
          <>
            <Badge tone="amber">{channel.language}</Badge>
            <Badge>Skill v{channel.stats.skill_version ?? 1}</Badge>
            <Badge>{usd(channel.stats.cost ?? 0, 2)} gastos</Badge>
          </>
        }
      />
      <div className="mb-6 flex overflow-x-auto border border-line bg-panel" role="tablist">
        {(
          [
            ["projects", "01", "Projetos"],
            ["skill", "02", "Skill"],
            ["learnings", "03", `Aprendizados${pending ? ` · ${pending}` : ""}`],
            ["settings", "04", "Configurações"],
          ] as [Tab, string, string][]
        ).map(([key, n, label]) => (
          <button key={key} role="tab" aria-selected={tab === key} className="slate-tab" onClick={() => setTab(key)}>
            <span className="font-mono text-[10px] tracking-[0.16em] text-amber">{n}</span>
            <span className="font-mono text-[11px] tracking-[0.14em] uppercase">{label}</span>
          </button>
        ))}
      </div>
      {(jobs.data?.jobs.length ?? 0) > 0 && (
        <Panel title="Tarefas do canal" className="mb-6" bodyClass="py-1">
          {jobs.data!.jobs.map((j) => (
            <JobLine key={j.id} job={j} showProject />
          ))}
        </Panel>
      )}
      {tab === "projects" && <ProjectsTab channel={channel} />}
      {tab === "skill" && <SkillTab channel={channel} />}
      {tab === "learnings" && <LearningsTab channel={channel} />}
      {tab === "settings" && <SettingsTab channel={channel} />}
    </div>
  );
}

function ProjectsTab({ channel }: { channel: Channel }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [quality, setQuality] = useState<Quality>(channel.default_quality);
  const [script, setScript] = useState("");
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["projects", channel.id], queryFn: () => api.get<ProjectSummary[]>(`/projects?channel_id=${channel.id}`) });
  const create = useMutation({
    mutationFn: () => api.post<ProjectSummary>("/projects", { channel_id: channel.id, title, quality, script }),
    onSuccess: (p) => {
      void qc.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/projetos/${p.id}`);
    },
  });
  return (
    <Panel
      index="01"
      title="Projetos"
      actions={
        <Btn variant="primary" size="sm" icon={<Plus size={12} />} onClick={() => setOpen(true)}>
          Novo projeto
        </Btn>
      }
      bodyClass="p-0"
    >
      {isLoading && <Loading />}
      {data && data.length === 0 && (
        <div className="p-4">
          <Empty title="Sem projetos" text="Cada projeto é um vídeo de ~15–25 minutos: roteiro, cenas, visuais, narração, thumbnail e metadados." action={<Btn variant="primary" onClick={() => setOpen(true)}>Criar projeto</Btn>} />
        </div>
      )}
      {data?.map((p) => (
        <Link key={p.id} to={`/projetos/${p.id}`} className="grid grid-cols-1 items-center gap-2 border-b border-line px-4 py-3.5 last:border-b-0 hover:bg-raised sm:grid-cols-[1fr_auto] sm:gap-3">
          <div className="min-w-0">
            <div className="truncate text-[15px] text-paper">{p.selected_title || p.title}</div>
            <div className="mt-0.5 text-[12px] text-dim">
              {p.words.toLocaleString("pt-BR")} palavras · {p.scenes ?? 0} cenas · atualizado {relative(p.updated_at)}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge tone="dim">{QUALITY_LABEL[p.quality]}</Badge>
            <Badge tone={p.status === "exported" ? "ok" : "default"}>{PROJECT_STATUS[p.status] ?? p.status}</Badge>
            <span className="tnum w-16 text-right font-mono text-[12px] text-dim" title="Espaço em disco">
              {bytes(p.size_bytes)}
            </span>
            <span className="tnum w-16 text-right font-mono text-[12px] text-muted">{usd(p.cost)}</span>
          </div>
        </Link>
      ))}
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Novo projeto"
        wide
        footer={
          <Btn variant="primary" disabled={!title.trim()} loading={create.isPending} onClick={() => create.mutate()}>
            Criar projeto
          </Btn>
        }
      >
        <div className="space-y-4">
          <Field label="Título de trabalho">
            <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} autoFocus placeholder="Ex.: O segredo da câmara de Boêmia" />
          </Field>
          <Field label="Nível de qualidade" hint="Você pode trocar depois; a estimativa dos três níveis aparece no projeto.">
            <Segmented<Quality>
              value={quality}
              onChange={setQuality}
              options={[
                { value: "ECONOMY", label: "Economy" },
                { value: "BALANCED", label: "Balanced" },
                { value: "PREMIUM", label: "Premium" },
              ]}
            />
          </Field>
          <Field label="Roteiro (opcional — pode colar depois)">
            <textarea className="input" rows={10} value={script} onChange={(e) => setScript(e.target.value)} placeholder={`Roteiro em ${channel.language}…`} />
          </Field>
          <ErrorBox error={create.error} />
        </div>
      </Modal>
    </Panel>
  );
}

function SkillTab({ channel }: { channel: Channel }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { data, isLoading } = useQuery({
    queryKey: ["skill", channel.id],
    queryFn: () => api.get<{ current: Skill | null; versions: { version: number; note: string; source: string; created_at: string; chars: number }[] }>(`/channels/${channel.id}/skill`),
  });
  const [content, setContent] = useState("");
  const [note, setNote] = useState("");
  const [mode, setMode] = useState<"edit" | "preview">("preview");
  const [compare, setCompare] = useState<Skill | null>(null);
  useEffect(() => {
    if (data?.current) setContent(data.current.content);
  }, [data?.current]);
  const dirty = !!data?.current && content !== data.current.content;
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["skill", channel.id] });
    void qc.invalidateQueries({ queryKey: ["channel", channel.id] });
  };
  const save = useMutation({
    mutationFn: () => api.put<Skill>(`/channels/${channel.id}/skill`, { content, note }),
    onSuccess: (s) => {
      toast(`Skill salva como v${s.version}`);
      setNote("");
      invalidate();
    },
    onError: (e) => toast(errorMessage(e), "err"),
  });
  const draft = useMutation({
    mutationFn: () => api.post(`/channels/${channel.id}/skill/draft`),
    onSuccess: () => {
      toast("A IA está escrevendo uma nova versão da Skill", "info");
      void qc.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (e) => toast(errorMessage(e), "err"),
  });
  const restore = useMutation({
    mutationFn: (v: number) => api.post<Skill>(`/channels/${channel.id}/skill/restore/${v}`),
    onSuccess: (s) => {
      toast(`Restaurada como v${s.version}`);
      setCompare(null);
      invalidate();
    },
  });
  async function openVersion(v: number) {
    setCompare(await api.get<Skill>(`/channels/${channel.id}/skill/${v}`));
  }

  if (isLoading) return <Loading />;
  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_320px]">
      <Panel
        index="02"
        title={`Skill v${data?.current?.version ?? 1}`}
        actions={
          <>
            <Segmented value={mode} onChange={setMode} options={[{ value: "preview", label: "Leitura" }, { value: "edit", label: "Editar" }]} />
            <Btn size="sm" icon={<Sparkles size={11} />} onClick={() => draft.mutate()} loading={draft.isPending} title="Gera uma nova versão a partir das configurações do canal (custo de 1 chamada de texto)">
              Gerar com IA
            </Btn>
          </>
        }
      >
        <Notice tone="info">
          A Skill é o manual do canal: entra em <strong>todas</strong> as chamadas de IA (análise, cenas, visuais, thumbnails, títulos). Aprendizados aprovados também
          entram automaticamente.
        </Notice>
        <div className="mt-4">
          {mode === "edit" ? (
            <textarea className="input min-h-[60vh] font-mono text-[13px] leading-relaxed" value={content} onChange={(e) => setContent(e.target.value)} />
          ) : (
            <div className="min-h-[40vh] border border-line bg-coal px-5 py-3">
              <MarkdownView text={content} />
            </div>
          )}
        </div>
        {dirty && (
          <div className="mt-4 flex flex-wrap items-end gap-3">
            <Field label="Nota da versão" className="min-w-64 flex-1">
              <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="O que mudou?" />
            </Field>
            <Btn onClick={() => setContent(data?.current?.content ?? "")}>Descartar</Btn>
            <Btn variant="primary" loading={save.isPending} onClick={() => save.mutate()}>
              Salvar nova versão
            </Btn>
          </div>
        )}
      </Panel>
      <Panel title="Histórico de versões" bodyClass="p-0">
        {data?.versions.map((v) => (
          <button key={v.version} onClick={() => void openVersion(v.version)} className="block w-full border-b border-line px-4 py-3 text-left last:border-b-0 hover:bg-raised">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[12px] text-amber">v{v.version}</span>
              <Badge tone="dim">{v.source}</Badge>
            </div>
            <div className="mt-1 line-clamp-2 text-[12.5px] text-muted">{v.note || "—"}</div>
            <div className="mt-1 font-mono text-[10.5px] text-dim">{dateTime(v.created_at)}</div>
          </button>
        ))}
      </Panel>
      <Modal
        open={!!compare}
        onClose={() => setCompare(null)}
        title={`v${compare?.version} → atual (v${data?.current?.version})`}
        wide
        footer={
          compare && compare.version !== data?.current?.version ? (
            <Btn variant="primary" icon={<RotateCcw size={12} />} onClick={() => restore.mutate(compare.version)} loading={restore.isPending}>
              Restaurar v{compare.version}
            </Btn>
          ) : undefined
        }
      >
        {compare && <LineDiff before={compare.content} after={data?.current?.content ?? ""} />}
      </Modal>
    </div>
  );
}

const CATEGORY_LABEL: Record<string, string> = {
  script: "Roteiro",
  scenes: "Cenas",
  visuals: "Visual",
  narration: "Narração",
  thumbnail: "Thumbnail",
  metadata: "Metadados",
  general: "Geral",
};

function LearningsTab({ channel }: { channel: Channel }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [text, setText] = useState("");
  const [category, setCategory] = useState("general");
  const { data, isLoading } = useQuery({ queryKey: ["learnings", channel.id], queryFn: () => api.get<Learning[]>(`/channels/${channel.id}/learnings`) });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["learnings", channel.id] });
    void qc.invalidateQueries({ queryKey: ["channel", channel.id] });
  };
  const update = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) => api.patch(`/channels/learnings/${id}`, { status }),
    onSuccess: refresh,
  });
  const add = useMutation({
    mutationFn: () => api.post(`/channels/${channel.id}/learnings`, { text, category }),
    onSuccess: () => {
      setText("");
      refresh();
    },
  });
  const remove = useMutation({ mutationFn: (id: number) => api.del(`/channels/learnings/${id}`), onSuccess: refresh });
  const consolidate = useMutation({
    mutationFn: () => api.post(`/channels/${channel.id}/skill/consolidate`),
    onSuccess: () => toast("Consolidando aprendizados numa nova versão da Skill", "info"),
    onError: (e) => toast(errorMessage(e), "err"),
  });
  if (isLoading || !data) return <Loading />;
  const groups: [string, string, Learning[]][] = [
    ["proposed", "Propostos pela IA — revise", data.filter((l) => l.status === "proposed")],
    ["accepted", "Aprovados (já entram nos prompts)", data.filter((l) => l.status === "accepted")],
    ["merged", "Incorporados na Skill", data.filter((l) => l.status === "merged")],
    ["rejected", "Rejeitados", data.filter((l) => l.status === "rejected")],
  ];
  const accepted = groups[1][2].length;

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_340px]">
      <div className="space-y-6">
        {groups.map(([key, label, items]) =>
          items.length === 0 && key !== "proposed" ? null : (
            <Panel key={key} title={`${label} · ${items.length}`} bodyClass="p-0">
              {items.length === 0 && <div className="px-4 py-6 text-[13px] text-dim">Nada para revisar. Ao exportar um projeto, a IA propõe aprendizados a partir das suas escolhas e edições.</div>}
              {items.map((l) => (
                <div key={l.id} className="grid grid-cols-[1fr_auto] gap-4 border-b border-line px-4 py-3 last:border-b-0">
                  <div className="min-w-0">
                    <div className="mb-1 flex items-center gap-2">
                      <Badge tone="dim">{CATEGORY_LABEL[l.category] ?? l.category}</Badge>
                      {l.project_id && (
                        <Link to={`/projetos/${l.project_id}`} className="font-mono text-[10.5px] text-dim hover:text-amber">
                          projeto #{l.project_id}
                        </Link>
                      )}
                    </div>
                    <div className={clsx("text-[14px]", l.status === "rejected" ? "text-dim line-through" : "text-paper")}>{l.text}</div>
                    {l.rationale && <div className="mt-1 text-[12.5px] text-muted">{l.rationale}</div>}
                  </div>
                  <div className="flex items-start gap-1.5">
                    {l.status !== "accepted" && l.status !== "merged" && (
                      <button className="btn btn-sm btn-icon" title="Aprovar" onClick={() => update.mutate({ id: l.id, status: "accepted" })}>
                        <Check size={12} />
                      </button>
                    )}
                    {l.status !== "rejected" && l.status !== "merged" && (
                      <button className="btn btn-sm btn-icon" title="Rejeitar" onClick={() => update.mutate({ id: l.id, status: "rejected" })}>
                        <X size={12} />
                      </button>
                    )}
                    <button className="btn btn-sm btn-icon" title="Excluir" onClick={() => remove.mutate(l.id)}>
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>
              ))}
            </Panel>
          ),
        )}
      </div>
      <div className="space-y-6">
        <Panel title="Consolidar na Skill">
          <p className="mb-3 text-[13px] text-muted">
            Reescreve a Skill integrando os {accepted} aprendizados aprovados. Gera uma nova versão — você pode comparar e restaurar a anterior.
          </p>
          <Btn variant="primary" disabled={!accepted} loading={consolidate.isPending} onClick={() => consolidate.mutate()} icon={<Sparkles size={12} />}>
            Consolidar {accepted} aprendizados
          </Btn>
        </Panel>
        <Panel title="Adicionar manualmente">
          <div className="space-y-3">
            <Field label="Categoria">
              <select className="input" value={category} onChange={(e) => setCategory(e.target.value)}>
                {Object.entries(CATEGORY_LABEL).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Regra">
              <textarea className="input" rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="Preferir cenas noturnas com luz de lampião…" />
            </Field>
            <Btn disabled={text.trim().length < 3} loading={add.isPending} onClick={() => add.mutate()} icon={<Plus size={12} />}>
              Adicionar (já aprovado)
            </Btn>
          </div>
        </Panel>
      </div>
    </div>
  );
}

function SettingsTab({ channel }: { channel: Channel }) {
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const [confirm, setConfirm] = useState("");
  const [deleting, setDeleting] = useState(false);
  const save = useMutation({
    mutationFn: (d: ChannelDraft) => api.patch<Channel>(`/channels/${channel.id}`, d),
    onSuccess: () => {
      toast("Canal atualizado");
      void qc.invalidateQueries({ queryKey: ["channel", channel.id] });
      void qc.invalidateQueries({ queryKey: ["channels"] });
    },
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/channels/${channel.id}?confirm=${encodeURIComponent(confirm)}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["channels"] });
      navigate("/canais");
    },
  });
  const { id: _id, slug: _slug, stats: _s, created_at: _c, updated_at: _u, archived: _a, default_wpm: _w, ...draft } = channel;
  return (
    <div className="space-y-6">
      <Panel index="04" title="Configurações do canal">
        <ChannelForm initial={draft} channelId={channel.id} onSubmit={(d) => save.mutate(d)} submitLabel="Salvar alterações" busy={save.isPending} error={save.error} />
      </Panel>
      <Panel title="Zona de perigo">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="max-w-xl text-[13px] text-muted">Excluir o canal remove definitivamente todos os projetos, cenas, arquivos gerados e a Skill. O histórico de custos é mantido.</p>
          <Btn variant="danger" icon={<Trash2 size={12} />} onClick={() => setDeleting(true)}>
            Excluir canal
          </Btn>
        </div>
      </Panel>
      <Modal
        open={deleting}
        onClose={() => setDeleting(false)}
        title="Excluir canal"
        footer={
          <Btn variant="danger" disabled={confirm !== channel.slug} loading={remove.isPending} onClick={() => remove.mutate()}>
            Excluir definitivamente
          </Btn>
        }
      >
        <p className="mb-3 text-[13px] text-muted">
          Digite <code className="font-mono text-amber">{channel.slug}</code> para confirmar.
        </p>
        <input className="input" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        <div className="mt-3">
          <ErrorBox error={remove.error} />
        </div>
      </Modal>
    </div>
  );
}
