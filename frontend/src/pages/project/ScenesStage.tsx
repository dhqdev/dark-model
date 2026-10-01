import { useMutation } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronDown, ChevronRight, Clapperboard, Image as ImageIcon, Mic, Sparkles, Trash2, Wand2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Badge, Btn, Empty, Field, Led, Modal, Notice, Panel, Segmented, useToast } from "../../components/ui";
import { api, errorMessage } from "../../lib/api";
import { ASSET_TYPE_LABEL, MOTION_LABEL, SFX_LABEL, TRANSITION_LABEL, minutes, secs, timecode } from "../../lib/format";
import type { AssetType, Motion, ProjectDetail, Scene } from "../../lib/types";
import { useInvalidateProject, useProjectAction } from "./shared";

const TYPES: { value: AssetType; label: string }[] = [
  { value: "IMAGE", label: "Imagem" },
  { value: "IMAGE_MOTION", label: "Img+Motion" },
  { value: "VIDEO", label: "Vídeo" },
];

export function ScenesStage({ project }: { project: ProjectDetail }) {
  const [confirm, setConfirm] = useState(false);
  const [filter, setFilter] = useState<"all" | AssetType>("all");
  const plan = useProjectAction<{ replace: boolean }>(project.id, "scenes/plan", "Divisão em cenas na fila");
  const scenes = project.scenes_list;
  const counts = useMemo(() => {
    const c: Record<string, number> = { IMAGE: 0, IMAGE_MOTION: 0, VIDEO: 0 };
    scenes.forEach((s) => (c[s.asset_type] += 1));
    return c;
  }, [scenes]);
  const total = scenes.reduce((s, x) => s + x.duration, 0);
  const shown = filter === "all" ? scenes : scenes.filter((s) => s.asset_type === filter);
  const running = project.active_jobs.some((j) => j.kind === "scenes.plan");

  return (
    <div className="space-y-6">
      <Panel
        index="02"
        title="Cenas"
        actions={
          <>
            <Segmented
              value={filter}
              onChange={setFilter}
              options={[
                { value: "all", label: `Todas ${scenes.length}` },
                { value: "IMAGE_MOTION", label: `Motion ${counts.IMAGE_MOTION}` },
                { value: "VIDEO", label: `Vídeo ${counts.VIDEO}` },
                { value: "IMAGE", label: `Imagem ${counts.IMAGE}` },
              ]}
            />
            <Btn
              variant="primary"
              size="sm"
              icon={<Clapperboard size={11} />}
              loading={plan.isPending || running}
              disabled={!project.stages.script.ready}
              onClick={() => (scenes.length ? setConfirm(true) : plan.mutate({ replace: false }))}
            >
              {scenes.length ? "Refazer cenas" : "Gerar cenas"}
            </Btn>
          </>
        }
        bodyClass="p-0"
      >
        <div className="flex flex-wrap gap-x-6 gap-y-1 border-b border-line px-4 py-2.5 font-mono text-[11px] text-muted">
          <span>
            <span className="text-paper">{scenes.length}</span> cenas
          </span>
          <span>
            duração <span className="text-paper">{minutes(total)}</span>
            {project.stages.narration.ready === scenes.length && scenes.length ? " (áudio real)" : " (estimada)"}
          </span>
          <span>
            média <span className="text-paper">{scenes.length ? secs(total / scenes.length) : "—"}</span>/cena
          </span>
          <span>
            vídeo IA <span className="text-paper">{counts.VIDEO}</span>
          </span>
        </div>
        {scenes.length > 0 && !project.stages.scenes.fresh && (
          <div className="border-b border-line p-3">
            <Notice tone="amber">O roteiro mudou depois da divisão em cenas. Refaça as cenas ou ajuste a narração manualmente.</Notice>
          </div>
        )}
        {scenes.length === 0 ? (
          <div className="p-4">
            <Empty
              title="Sem cenas"
              text="A IA divide o roteiro em cenas com trecho da narração, duração, descrição visual, prompt e o melhor tipo de asset (Imagem, Imagem + Motion ou Vídeo)."
            />
          </div>
        ) : (
          shown.map((s) => <SceneRow key={s.id} scene={s} project={project} />)
        )}
      </Panel>
      <Modal
        open={confirm}
        onClose={() => setConfirm(false)}
        title="Refazer todas as cenas?"
        footer={
          <Btn
            variant="danger"
            onClick={() => {
              plan.mutate({ replace: true });
              setConfirm(false);
            }}
          >
            Refazer e apagar assets das cenas
          </Btn>
        }
      >
        <p className="text-[13px] text-muted">
          As {scenes.length} cenas atuais e seus arquivos (imagens, vídeos e narrações) serão substituídos. Para ajustar só uma cena, use “Reescrever com IA” na própria
          cena.
        </p>
      </Modal>
    </div>
  );
}

function SceneRow({ scene, project }: { scene: Scene; project: ProjectDetail }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(scene);
  const [instruction, setInstruction] = useState("");
  const toast = useToast();
  const invalidate = useInvalidateProject(project.id);
  useEffect(() => setDraft(scene), [scene]);
  const dirty =
    draft.narration !== scene.narration ||
    draft.visual_description !== scene.visual_description ||
    draft.prompt !== scene.prompt ||
    draft.asset_type !== scene.asset_type ||
    draft.motion !== scene.motion ||
    draft.transition !== scene.transition ||
    draft.sfx !== scene.sfx ||
    draft.overlay_text !== scene.overlay_text;
  const busy = project.active_jobs.some((j) => j.scene_id === scene.id);

  const save = useMutation({
    mutationFn: () =>
      api.patch(`/scenes/${scene.id}`, {
        narration: draft.narration,
        visual_description: draft.visual_description,
        prompt: draft.prompt,
        asset_type: draft.asset_type,
        motion: draft.motion,
        transition: draft.transition,
        sfx: draft.sfx,
        overlay_text: draft.overlay_text,
      }),
    onSuccess: () => {
      toast(`Cena ${scene.position} salva`);
      invalidate();
    },
    onError: (e) => toast(errorMessage(e), "err"),
  });
  const action = (path: string, body: unknown, msg: string) =>
    api
      .post<{ job?: unknown; message?: string }>(`/scenes/${scene.id}/${path}`, body)
      .then((r) => {
        toast(r.message || msg, r.message ? "info" : "ok");
        invalidate();
      })
      .catch((e) => toast(errorMessage(e), "err"));
  const remove = useMutation({
    mutationFn: () => api.del(`/scenes/${scene.id}`),
    onSuccess: invalidate,
  });

  return (
    <div className={clsx("border-b border-line last:border-b-0", open && "bg-raised/40")}>
      <button className="grid w-full grid-cols-[22px_52px_1fr_auto] items-start gap-3 px-4 py-3 text-left hover:bg-raised md:grid-cols-[22px_120px_1fr_150px_96px]" onClick={() => setOpen((v) => !v)}>
        <span className="pt-0.5 text-dim">{open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</span>
        <div className="font-mono text-[11px] leading-tight">
          <div className="text-amber">#{String(scene.position).padStart(3, "0")}</div>
          <div className="tnum hidden text-dim md:block">{timecode(scene.start)}</div>
          <div className="tnum text-muted">{secs(scene.duration)}</div>
        </div>
        <div className="min-w-0">
          <div className="line-clamp-2 text-[13.5px] text-paper">{scene.narration}</div>
          <div className="mt-0.5 line-clamp-1 text-[12px] text-dim">{scene.visual_description}</div>
        </div>
        <div className="hidden flex-col items-start gap-1 md:flex">
          <Badge tone={scene.asset_type === "VIDEO" ? "amber" : "default"}>{ASSET_TYPE_LABEL[scene.asset_type]}</Badge>
          {scene.asset_type !== scene.ai_asset_type && <span className="font-mono text-[10px] text-dim">IA: {ASSET_TYPE_LABEL[scene.ai_asset_type]}</span>}
          <span className="font-mono text-[10px] text-dim">
            {scene.position > 1 ? TRANSITION_LABEL[scene.transition] ?? scene.transition : "abre do preto"}
            {scene.sfx !== "none" ? ` · ♪ ${SFX_LABEL[scene.sfx] ?? scene.sfx}` : ""}
            {scene.overlay_text ? " · T" : ""}
          </span>
        </div>
        <div className="flex items-center justify-end gap-2">
          {scene.image?.url && <img src={scene.image.url} alt="" loading="lazy" className="hidden aspect-video w-14 border border-line object-cover sm:block" />}
          <div className="flex flex-col gap-1.5" title="visual · narração">
            <Led status={busy ? "running" : scene.visual_ready ? "ok" : scene.image ? "queued" : "off"} title={scene.visual_ready ? "Visual pronto" : scene.image ? "Visual desatualizado/incompleto" : "Sem visual"} />
            <Led status={scene.audio_ok ? "ok" : scene.audio ? "queued" : "off"} title={scene.audio_ok ? "Narração pronta" : "Sem narração atualizada"} />
          </div>
        </div>
      </button>
      {open && (
        <div className="grid gap-4 px-4 pt-1 pb-5 md:pl-[58px] xl:grid-cols-2">
          <Field label={`Narração · ${scene.words} palavras`}>
            <textarea className="input text-[13.5px]" rows={4} value={draft.narration} onChange={(e) => setDraft({ ...draft, narration: e.target.value })} />
          </Field>
          <Field label="Descrição visual">
            <textarea className="input text-[13.5px]" rows={4} value={draft.visual_description} onChange={(e) => setDraft({ ...draft, visual_description: e.target.value })} />
          </Field>
          <Field label="Prompt (inglês)" className="xl:col-span-2">
            <textarea className="input font-mono text-[12.5px]" rows={3} value={draft.prompt} onChange={(e) => setDraft({ ...draft, prompt: e.target.value })} />
          </Field>
          <div className="flex flex-wrap items-end gap-4 xl:col-span-2">
            <Field label="Tipo de asset">
              <Segmented value={draft.asset_type} onChange={(v) => setDraft({ ...draft, asset_type: v })} options={TYPES} />
            </Field>
            <Field label="Movimento">
              <select className="input w-36" value={draft.motion} onChange={(e) => setDraft({ ...draft, motion: e.target.value as Motion })}>
                {Object.entries(MOTION_LABEL).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </Field>
            <div className="min-w-60 flex-1 text-[12.5px] text-muted">
              <span className="kicker mr-2">IA sugeriu {ASSET_TYPE_LABEL[scene.ai_asset_type]}</span>
              {scene.asset_type_reason}
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-[160px_180px_1fr] xl:col-span-2">
            <Field label={scene.position === 1 ? "Entrada (abre do preto)" : "Transição de entrada"}>
              <select className="input" value={draft.transition} disabled={scene.position === 1} onChange={(e) => setDraft({ ...draft, transition: e.target.value })}>
                {Object.entries(TRANSITION_LABEL).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Efeito sonoro">
              <select className="input" value={draft.sfx} onChange={(e) => setDraft({ ...draft, sfx: e.target.value })}>
                {Object.entries(SFX_LABEL).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Texto na tela (máquina de escrever) · vazio = sem texto">
              <input className="input" maxLength={60} placeholder="ex.: 10 de maio de 1869 · Utah" value={draft.overlay_text} onChange={(e) => setDraft({ ...draft, overlay_text: e.target.value })} />
            </Field>
          </div>
          <div className="flex flex-wrap items-center gap-2 xl:col-span-2">
            <Btn variant="primary" size="sm" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>
              Salvar cena
            </Btn>
            <Btn size="sm" icon={<ImageIcon size={11} />} disabled={dirty || busy} onClick={() => void action("visual", { force: true }, "Visual da cena na fila")}>
              Gerar visual
            </Btn>
            <Btn size="sm" icon={<Mic size={11} />} disabled={dirty || busy} onClick={() => void action("narration", {}, "Narração da cena na fila")}>
              Narrar
            </Btn>
            <div className="flex min-w-72 flex-1 items-center gap-2">
              <input className="input py-1.5 text-[12.5px]" placeholder="Instrução para a IA (opcional): mais sombrio, mostrar um mapa…" value={instruction} onChange={(e) => setInstruction(e.target.value)} />
              <Btn size="sm" icon={<Wand2 size={11} />} disabled={busy} onClick={() => void action("rewrite", { instruction }, "Nova proposta visual na fila").then(() => setInstruction(""))}>
                Reescrever
              </Btn>
            </div>
            <Btn size="sm" variant="danger" icon={<Trash2 size={11} />} onClick={() => remove.mutate()}>
              Excluir
            </Btn>
          </div>
          {dirty && (
            <div className="xl:col-span-2">
              <Notice tone="amber">
                <Sparkles size={12} className="mr-1 inline" />
                Alterações não salvas. Mudanças no prompt ou tipo deixam o visual atual desatualizado; mudanças na narração, o áudio.
              </Notice>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
