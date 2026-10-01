import { useMutation } from "@tanstack/react-query";
import clsx from "clsx";
import { Plus, Star, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Btn, Empty, Field, Panel, useToast } from "../../components/ui";
import { api, errorMessage } from "../../lib/api";
import { usd } from "../../lib/format";
import type { Concept, ProjectDetail } from "../../lib/types";
import { useInvalidateProject, useProjectAction } from "./shared";

export function ThumbnailStage({ project }: { project: ProjectDetail }) {
  const [count, setCount] = useState(3);
  const [variations, setVariations] = useState(2);
  const run = useProjectAction<{ count: number; variations: number }>(project.id, "thumbnails", "Thumbnails na fila");
  const running = project.active_jobs.some((j) => j.kind === "thumbnail.batch");
  return (
    <div className="space-y-6">
      <Panel
        index="06"
        title="Thumbnails"
        actions={
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex items-center gap-2 font-mono text-[10.5px] text-muted uppercase">
              conceitos
              <input className="input w-14 py-1 text-center" type="number" min={1} max={8} value={count} onChange={(e) => setCount(Number(e.target.value))} />
            </label>
            <label className="flex items-center gap-2 font-mono text-[10.5px] text-muted uppercase">
              variações
              <input className="input w-14 py-1 text-center" type="number" min={1} max={4} value={variations} onChange={(e) => setVariations(Number(e.target.value))} />
            </label>
            <Btn variant="primary" size="sm" loading={run.isPending || running} disabled={!project.stages.script.ready} onClick={() => run.mutate({ count, variations })}>
              Gerar conceitos
            </Btn>
          </div>
        }
      >
        <div className="text-[12.5px] text-muted">
          A IA cria conceitos (ideia, emoção, composição, texto e prompt) e gera as imagens em 1280×720. Marque a favorita de cada conceito com ★ — suas escolhas
          alimentam os aprendizados da Skill.
          {project.channel.thumbnail_text_mode === "none" ? " O texto não é desenhado na imagem (canal configurado para adicionar depois)." : ""}
        </div>
      </Panel>
      {project.concepts.length === 0 ? (
        <Empty title="Nenhum conceito ainda" text="Gere conceitos depois de finalizar o roteiro — e de preferência depois dos títulos, para combinar com eles." />
      ) : (
        project.concepts.map((c) => <ConceptCard key={c.id} concept={c} project={project} />)
      )}
    </div>
  );
}

function ConceptCard({ concept, project }: { concept: Concept; project: ProjectDetail }) {
  const toast = useToast();
  const invalidate = useInvalidateProject(project.id);
  const [overlay, setOverlay] = useState(concept.overlay_text);
  const [prompt, setPrompt] = useState(concept.prompt);
  useEffect(() => {
    setOverlay(concept.overlay_text);
    setPrompt(concept.prompt);
  }, [concept.overlay_text, concept.prompt]);
  const dirty = overlay !== concept.overlay_text || prompt !== concept.prompt;
  const busy = project.active_jobs.some((j) => j.kind === "thumbnail.batch") || project.active_jobs.some((j) => j.target_id === concept.id);
  const onErr = (e: unknown) => toast(errorMessage(e), "err");
  const save = useMutation({ mutationFn: () => api.patch(`/thumbnails/${concept.id}`, { overlay_text: overlay, prompt }), onSuccess: invalidate, onError: onErr });
  const more = useMutation({
    mutationFn: () => api.post(`/thumbnails/${concept.id}/generate`, { variations: 1 }),
    onSuccess: () => {
      toast("Nova variação na fila", "info");
      invalidate();
    },
    onError: onErr,
  });
  const select = useMutation({ mutationFn: (assetId: number) => api.post(`/thumbnails/${concept.id}/select`, { asset_id: assetId }), onSuccess: invalidate, onError: onErr });
  const remove = useMutation({ mutationFn: () => api.del(`/thumbnails/${concept.id}`), onSuccess: invalidate, onError: onErr });

  return (
    <Panel
      title={concept.name}
      index={`C${concept.position}`}
      actions={
        <>
          {concept.emotion && <Badge tone="dim">{concept.emotion}</Badge>}
          <Btn size="sm" icon={<Plus size={11} />} loading={more.isPending} onClick={() => more.mutate()} disabled={dirty}>
            Variação
          </Btn>
          <button className="btn btn-sm btn-icon" title="Excluir conceito" onClick={() => remove.mutate()}>
            <Trash2 size={11} />
          </button>
        </>
      }
    >
      <div className="grid gap-5 xl:grid-cols-[1fr_1.4fr]">
        <div className="space-y-3 text-[13px]">
          <div>
            <div className="kicker mb-1">Ideia</div>
            <div className="text-paper">{concept.idea}</div>
          </div>
          <div>
            <div className="kicker mb-1">Composição</div>
            <div className="text-muted">{concept.composition}</div>
          </div>
          <div className="text-[12.5px] text-dim">{concept.rationale}</div>
          <Field label="Texto da thumbnail">
            <input className="input font-mono uppercase" value={overlay} onChange={(e) => setOverlay(e.target.value)} maxLength={120} />
          </Field>
          <Field label="Prompt">
            <textarea className="input font-mono text-[12px]" rows={4} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          </Field>
          {dirty && (
            <Btn size="sm" variant="primary" loading={save.isPending} onClick={() => save.mutate()}>
              Salvar conceito
            </Btn>
          )}
        </div>
        <div className="grid content-start gap-3 sm:grid-cols-2">
          {concept.images.length === 0 && <div className="flex aspect-video items-center justify-center border border-dashed border-edge font-mono text-[11px] text-dim uppercase">{busy ? "gerando…" : "sem imagens"}</div>}
          {concept.images.map((img) => {
            const chosen = concept.selected_asset_id === img.id;
            return (
              <button key={img.id} onClick={() => select.mutate(img.id)} className={clsx("group relative border-2 text-left", chosen ? "border-amber" : "border-transparent hover:border-edge")}>
                <img src={img.url} alt={concept.name} loading="lazy" className="aspect-video w-full object-cover" />
                <span className={clsx("absolute top-2 left-2 flex items-center gap-1 bg-ink/85 px-1.5 py-1 font-mono text-[10px] uppercase", chosen ? "text-amber" : "text-dim group-hover:text-paper")}>
                  <Star size={11} fill={chosen ? "currentColor" : "none"} /> {chosen ? "Escolhida" : "Escolher"}
                </span>
                <span className="absolute right-2 bottom-2 bg-ink/85 px-1.5 py-0.5 font-mono text-[10px] text-dim">{usd(img.cost)}</span>
              </button>
            );
          })}
        </div>
      </div>
    </Panel>
  );
}
