import { useMutation } from "@tanstack/react-query";
import clsx from "clsx";
import { Sparkles, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Btn, Empty, Field, Notice, Panel, useToast } from "../../components/ui";
import { api, errorMessage } from "../../lib/api";
import type { ProjectDetail } from "../../lib/types";
import { useInvalidateProject, useProjectAction } from "./shared";

export function MetadataStage({ project }: { project: ProjectDetail }) {
  const run = useProjectAction(project.id, "metadata", "Títulos e descrição na fila");
  const toast = useToast();
  const invalidate = useInvalidateProject(project.id);
  const meta = project.metadata_suggestions;
  const [title, setTitle] = useState(project.selected_title);
  const [description, setDescription] = useState(project.description);
  const [tags, setTags] = useState<string[]>(project.tags);
  const [tagInput, setTagInput] = useState("");
  useEffect(() => {
    setTitle(project.selected_title);
    setDescription(project.description);
    setTags(project.tags);
  }, [project.selected_title, project.description, project.tags]);
  const dirty = title !== project.selected_title || description !== project.description || tags.join("|") !== project.tags.join("|");
  const save = useMutation({
    mutationFn: () => api.patch(`/projects/${project.id}`, { selected_title: title, description, tags }),
    onSuccess: () => {
      toast("Metadados salvos");
      invalidate();
    },
    onError: (e) => toast(errorMessage(e), "err"),
  });
  const tagChars = tags.reduce((s, t) => s + t.length + (t.includes(" ") ? 2 : 0) + 1, 0);
  const running = project.active_jobs.some((j) => j.kind === "metadata.generate");

  function addTags(raw: string) {
    const next = raw
      .split(",")
      .map((t) => t.trim().replace(/^#/, ""))
      .filter(Boolean);
    setTags((xs) => [...xs, ...next.filter((t) => !xs.some((x) => x.toLowerCase() === t.toLowerCase()))]);
    setTagInput("");
  }

  return (
    <div className="space-y-6">
      <Panel
        index="06"
        title="Título, descrição e tags"
        actions={
          <>
            <Btn size="sm" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>
              Salvar
            </Btn>
            <Btn variant="primary" size="sm" icon={<Sparkles size={11} />} loading={run.isPending || running} disabled={!project.stages.script.ready} onClick={() => run.mutate(undefined)}>
              {meta ? "Gerar novas sugestões" : "Gerar sugestões"}
            </Btn>
          </>
        }
      >
        {!meta && <Empty title="Sem sugestões ainda" text="Gere depois da narração para que os capítulos usem os tempos reais do áudio." />}
        {meta && (
          <div className="space-y-6">
            {meta.policy_notes.length > 0 && (
              <Notice tone="amber">
                {meta.policy_notes.map((n, i) => (
                  <div key={i}>• {n}</div>
                ))}
              </Notice>
            )}
            {meta.timeline_source === "estimate" && <Notice tone="info">Capítulos com tempos estimados — gere a narração e as sugestões novamente para usar os tempos reais.</Notice>}
            <section>
              <div className="label">Títulos sugeridos</div>
              <div className="divide-y divide-line border border-line">
                {meta.titles.map((t, i) => {
                  const len = t.title.length;
                  return (
                    <label key={i} className={clsx("flex cursor-pointer items-center gap-3 px-3 py-2.5 hover:bg-raised", title === t.title && "bg-amber/5")}>
                      <input type="radio" name="title" className="accent-amber" checked={title === t.title} onChange={() => setTitle(t.title)} />
                      <span className="flex-1 text-[14px] text-paper">{t.title}</span>
                      <Badge tone="dim">{t.angle}</Badge>
                      <span className={clsx("tnum w-10 text-right font-mono text-[11px]", len > 100 ? "text-signal" : len > 70 ? "text-amber" : "text-dim")}>{len}</span>
                    </label>
                  );
                })}
              </div>
              <Field label="Título final" className="mt-3" hint={`${title.length}/100 caracteres · ideal até 70`}>
                <input className="input text-[15px]" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={100} />
              </Field>
            </section>
            <section>
              <div className="mb-1.5 flex items-end justify-between">
                <span className="label mb-0">Descrição</span>
                <button className="font-mono text-[10.5px] text-dim uppercase hover:text-amber" onClick={() => setDescription(meta.description)}>
                  restaurar sugestão
                </button>
              </div>
              <textarea className="input min-h-[300px] text-[13.5px]" value={description} onChange={(e) => setDescription(e.target.value)} />
              <div className={clsx("mt-1 text-right font-mono text-[11px]", description.length > 5000 ? "text-signal" : "text-dim")}>{description.length}/5000</div>
            </section>
            <section className="grid gap-6 lg:grid-cols-2">
              <div>
                <div className="label">Tags · {tagChars}/500 caracteres</div>
                <div className="flex flex-wrap gap-1.5 border border-line bg-coal p-2">
                  {tags.map((t) => (
                    <span key={t} className="inline-flex items-center gap-1 border border-edge px-2 py-0.5 text-[12.5px]">
                      {t}
                      <button onClick={() => setTags((xs) => xs.filter((x) => x !== t))} className="text-dim hover:text-signal" aria-label={`remover ${t}`}>
                        <X size={11} />
                      </button>
                    </span>
                  ))}
                  <input
                    className="min-w-32 flex-1 bg-transparent px-1 text-[12.5px] outline-none"
                    placeholder="adicionar (Enter ou vírgula)"
                    value={tagInput}
                    onChange={(e) => (e.target.value.endsWith(",") ? addTags(e.target.value) : setTagInput(e.target.value))}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        addTags(tagInput);
                      }
                    }}
                  />
                </div>
                <div className="mt-3 text-[12.5px] text-muted">
                  <span className="kicker mr-2">Hashtags</span>
                  {meta.hashtags.join(" ")}
                </div>
              </div>
              <div className="space-y-3">
                <div>
                  <div className="label">Capítulos</div>
                  <div className="font-mono text-[12.5px]">
                    {meta.chapters.length ? (
                      meta.chapters.map((c) => (
                        <div key={c.scene}>
                          <span className="text-amber">{c.time}</span> {c.title}
                        </div>
                      ))
                    ) : (
                      <span className="text-dim">Crie as cenas para gerar capítulos.</span>
                    )}
                  </div>
                </div>
                <div className="text-[12.5px]">
                  <span className="kicker mr-2">Palavras-chave</span>
                  <span className="text-paper">{meta.primary_keywords.join(", ")}</span>
                  <span className="text-dim"> · {meta.secondary_keywords.join(", ")}</span>
                </div>
              </div>
            </section>
          </div>
        )}
      </Panel>
    </div>
  );
}
