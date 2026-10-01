import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Film, Image as ImageIcon, Layers, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Badge, Btn, Empty, Led, Modal, Panel, Segmented, useToast } from "../../components/ui";
import { api, errorMessage } from "../../lib/api";
import { ASSET_TYPE_LABEL, brl, dateTime, MOTION_LABEL, secs, usd } from "../../lib/format";
import type { Asset, ProjectDetail, Scene } from "../../lib/types";
import { useInvalidateProject, useProjectAction } from "./shared";

export function Preview({ scene }: { scene: Scene }) {
  const clip = scene.clip && (scene.asset_type === "VIDEO" ? scene.clip.kind === "video" : scene.asset_type === "IMAGE_MOTION" ? scene.clip.kind === "motion" : false) ? scene.clip : null;
  if (clip) {
    return (
      <video
        src={clip.url}
        poster={scene.image?.url}
        muted
        loop
        playsInline
        preload="none"
        className="aspect-video w-full bg-coal object-cover"
        onMouseEnter={(e) => void e.currentTarget.play().catch(() => undefined)}
        onMouseLeave={(e) => e.currentTarget.pause()}
      />
    );
  }
  if (scene.image) return <img src={scene.image.url} alt={scene.visual_description} loading="lazy" className="aspect-video w-full bg-coal object-cover" />;
  return (
    <div className="flex aspect-video w-full flex-col items-center justify-center gap-1 bg-coal">
      <span className="font-mono text-[11px] tracking-[0.3em] text-dim uppercase">Sem sinal</span>
      <span className="font-mono text-[10px] text-dim">{ASSET_TYPE_LABEL[scene.asset_type]}</span>
    </div>
  );
}

export function VisualsStage({ project }: { project: ProjectDetail }) {
  const [filter, setFilter] = useState<"all" | "pending" | "ready">("all");
  const [confirmAll, setConfirmAll] = useState(false);
  const [versions, setVersions] = useState<Scene | null>(null);
  const run = useProjectAction<{ scope: string }>(project.id, "visuals", "Visuais na fila");
  const scenes = project.scenes_list;
  const ready = scenes.filter((s) => s.visual_ready).length;
  const shown = scenes.filter((s) => (filter === "all" ? true : filter === "ready" ? s.visual_ready : !s.visual_ready));
  const busyScenes = new Set(project.active_jobs.flatMap((j) => (j.scene_id ? [j.scene_id] : [])));
  const groupRunning = project.active_jobs.some((j) => j.kind === "visuals.batch");

  if (!scenes.length) return <Empty title="Crie as cenas primeiro" text="Os visuais são gerados por cena, a partir do prompt de cada uma." />;

  return (
    <Panel
      index="03"
      title={`Imagens e vídeos · ${ready}/${scenes.length}`}
      actions={
        <>
          <Segmented
            value={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: "Todas" },
              { value: "pending", label: `Pendentes ${scenes.length - ready}` },
              { value: "ready", label: `Prontas ${ready}` },
            ]}
          />
          <Btn size="sm" icon={<RefreshCw size={11} />} onClick={() => setConfirmAll(true)} disabled={groupRunning}>
            Regenerar tudo
          </Btn>
          <Btn variant="primary" size="sm" icon={<ImageIcon size={11} />} loading={run.isPending || groupRunning} disabled={ready === scenes.length} onClick={() => run.mutate({ scope: "missing" })}>
            Gerar pendentes
          </Btn>
        </>
      }
    >
      <div className="mb-4 text-[12.5px] text-muted">
        Imagem + Motion: imagem gerada por IA animada localmente (zoom/pan, sem custo extra). Vídeo: clipe gerado por IA a partir da imagem da cena (quando o modelo aceita
        quadro inicial). Passe o mouse sobre um clipe para assistir.
      </div>
      {project.plan && project.plan.tier === project.quality && (
        <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1 border border-line bg-coal px-3 py-2 font-mono text-[11.5px] text-muted">
          <span className="kicker">Plano do nível</span>
          <span>
            imagem <span className="text-paper">{project.plan.image_model ?? "—"}</span> · {project.plan.image_resolution}
          </span>
          {project.plan.cap_brl ? (
            <span className={project.plan.fits === false ? "text-signal" : "text-ok"}>
              teto {brl(project.plan.cap_brl)} · estimado {brl(project.plan.total_brl)}
            </span>
          ) : (
            <span>sem teto</span>
          )}
          {project.plan.adjustments.length > 0 && <span className="text-dim">ajustes: {project.plan.adjustments.join(" · ")}</span>}
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
        {shown.map((s) => (
          <SceneCard key={s.id} scene={s} project={project} busy={busyScenes.has(s.id)} onVersions={() => setVersions(s)} />
        ))}
      </div>
      <Modal
        open={confirmAll}
        onClose={() => setConfirmAll(false)}
        title="Regenerar todos os visuais?"
        footer={
          <Btn
            variant="danger"
            onClick={() => {
              run.mutate({ scope: "all" });
              setConfirmAll(false);
            }}
          >
            Regenerar {scenes.length} cenas
          </Btn>
        }
      >
        <p className="text-[13px] text-muted">Isso gera novas imagens (e vídeos IA) para todas as cenas, inclusive as prontas. Confira o custo estimado na aba Custos.</p>
      </Modal>
      {versions && <VersionsModal scene={versions} projectId={project.id} onClose={() => setVersions(null)} />}
    </Panel>
  );
}

function SceneCard({ scene, project, busy, onVersions }: { scene: Scene; project: ProjectDetail; busy: boolean; onVersions: () => void }) {
  const toast = useToast();
  const invalidate = useInvalidateProject(project.id);
  const act = (step: "image" | "clip") =>
    api
      .post(`/scenes/${scene.id}/visual`, { step })
      .then(() => {
        toast(`Cena ${scene.position}: ${step === "image" ? "nova imagem" : "novo clipe"} na fila`, "info");
        invalidate();
      })
      .catch((e) => toast(errorMessage(e), "err"));
  const status = busy ? "running" : scene.visual_ready ? "ok" : scene.image ? "queued" : "off";
  const cost = (scene.image?.cost ?? 0) + (scene.clip?.cost ?? 0);
  return (
    <div className={clsx("panel overflow-hidden", busy && "border-amber/50")}>
      <div className="relative">
        <Preview scene={scene} />
        <div className="absolute top-2 left-2 flex items-center gap-1.5 bg-ink/80 px-1.5 py-1 font-mono text-[10.5px] text-amber">#{String(scene.position).padStart(3, "0")}</div>
        <div className="absolute top-2 right-2">
          <Badge tone={scene.asset_type === "VIDEO" ? "amber" : "default"} className="bg-ink/80">
            {scene.asset_type === "VIDEO" ? <Film size={10} /> : null}
            {ASSET_TYPE_LABEL[scene.asset_type]}
          </Badge>
        </div>
      </div>
      <div className="space-y-2 p-3">
        <div className="line-clamp-2 min-h-[2.5em] text-[12.5px] text-muted">{scene.visual_description}</div>
        <div className="flex items-center justify-between font-mono text-[10.5px] text-dim">
          <span className="flex items-center gap-2">
            <Led status={status} /> {busy ? "gerando" : scene.visual_ready ? "pronto" : scene.image ? "desatualizado" : "pendente"}
          </span>
          <span>
            {secs(scene.duration)} · {scene.asset_type === "IMAGE_MOTION" ? MOTION_LABEL[scene.motion] : ""} {cost ? usd(cost) : ""}
          </span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Btn size="sm" disabled={busy} onClick={() => void act("image")}>
            Imagem
          </Btn>
          {scene.asset_type !== "IMAGE" && (
            <Btn size="sm" disabled={busy || !scene.image} onClick={() => void act("clip")}>
              {scene.asset_type === "VIDEO" ? "Vídeo" : "Motion"}
            </Btn>
          )}
          <Btn size="sm" icon={<Layers size={11} />} onClick={onVersions}>
            Versões
          </Btn>
        </div>
      </div>
    </div>
  );
}

function VersionsModal({ scene, projectId, onClose }: { scene: Scene; projectId: number; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { data } = useQuery({ queryKey: ["scene-assets", scene.id], queryFn: () => api.get<Asset[]>(`/scenes/${scene.id}/assets`) });
  const visuals = (data ?? []).filter((a) => a.kind !== "audio");
  async function select(a: Asset) {
    try {
      await api.post(`/scenes/${scene.id}/select`, { asset_id: a.id });
      toast("Versão escolhida");
      void qc.invalidateQueries({ queryKey: ["project", projectId] });
      void qc.invalidateQueries({ queryKey: ["scene-assets", scene.id] });
    } catch (e) {
      toast(errorMessage(e), "err");
    }
  }
  const selected = new Set([scene.image?.id, scene.clip?.id]);
  return (
    <Modal open onClose={onClose} title={`Cena ${scene.position} · versões`} wide>
      {!visuals.length && <div className="text-[13px] text-dim">Nenhuma versão gerada ainda.</div>}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {visuals.map((a) => (
          <div key={a.id} className={clsx("border", selected.has(a.id) ? "border-amber" : "border-line")}>
            {a.mime.startsWith("video") ? <video src={a.url} controls preload="none" className="aspect-video w-full bg-coal" /> : <img src={a.url} alt="" loading="lazy" className="aspect-video w-full object-cover" />}
            <div className="flex items-center justify-between gap-2 p-2 font-mono text-[10.5px] text-dim">
              <span>
                {a.kind} · {a.model || "local"} · {usd(a.cost)} · {dateTime(a.created_at)}
              </span>
              {selected.has(a.id) ? (
                <Badge tone="amber">em uso</Badge>
              ) : (
                <Btn size="sm" onClick={() => void select(a)}>
                  Usar
                </Btn>
              )}
            </div>
          </div>
        ))}
      </div>
    </Modal>
  );
}
