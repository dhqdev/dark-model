import clsx from "clsx";
import { Mic, Music } from "lucide-react";
import { Link } from "react-router";
import { Badge, Btn, Empty, Led, Notice, Panel, useToast } from "../../components/ui";
import { api, errorMessage } from "../../lib/api";
import { minutes, secs, timecode, usd } from "../../lib/format";
import type { ProjectDetail } from "../../lib/types";
import { useInvalidateProject, useProjectAction } from "./shared";

export function NarrationStage({ project }: { project: ProjectDetail }) {
  const run = useProjectAction<{ scope: string }>(project.id, "narration", "Narração na fila");
  const merge = useProjectAction<{ gap: number }>(project.id, "narration/merge", "Montando narração completa");
  const toast = useToast();
  const invalidate = useInvalidateProject(project.id);
  const scenes = project.scenes_list;
  const ready = scenes.filter((s) => s.audio_ok).length;
  const real = scenes.reduce((s, x) => s + (x.audio_duration ?? 0), 0);
  const est = scenes.reduce((s, x) => s + x.est_duration, 0);
  const busyScenes = new Set(project.active_jobs.flatMap((j) => (j.scene_id ? [j.scene_id] : [])));
  const groupRunning = project.active_jobs.some((j) => j.kind === "narration.batch");
  const full = project.stages.narration.full;

  if (!scenes.length) return <Empty title="Crie as cenas primeiro" text="A narração é gerada por cena, o que facilita regenerar só um trecho." />;

  return (
    <div className="space-y-6">
      <Panel
        index="04"
        title={`Narração · ${ready}/${scenes.length}`}
        actions={
          <>
            <Btn size="sm" onClick={() => run.mutate({ scope: "all" })} disabled={groupRunning}>
              Renarrar tudo
            </Btn>
            <Btn variant="primary" size="sm" icon={<Mic size={11} />} loading={run.isPending || groupRunning} disabled={ready === scenes.length} onClick={() => run.mutate({ scope: "missing" })}>
              Narrar pendentes
            </Btn>
          </>
        }
      >
        {ready === scenes.length && (project.stages.render.running || project.stages.render.last) && (
          <div className="mb-4">
            <Notice tone="ok">
              {project.stages.render.running ? "Narração completa — o vídeo final está sendo montado. " : "Vídeo final pronto para baixar. "}
              <Link to={`/projetos/${project.id}?etapa=video`} className="text-amber underline-offset-2 hover:underline">
                Abrir vídeo final →
              </Link>
            </Notice>
          </div>
        )}
        <div className="mb-4 grid gap-4 md:grid-cols-[1fr_auto]">
          <div className="space-y-1.5 text-[13px]">
            {project.tts ? (
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="amber">{project.tts.model}</Badge>
                <Badge>voz {project.tts.voice ?? "padrão"}</Badge>
                <Badge>{project.tts.speed.toFixed(2)}×</Badge>
                {project.tts.style && <Badge tone="dim">estilo: {project.tts.style.slice(0, 40)}</Badge>}
                <Link to={`/canais/${project.channel_id}`} className="font-mono text-[10.5px] text-dim underline-offset-2 hover:text-amber hover:underline">
                  alterar voz no canal
                </Link>
              </div>
            ) : (
              <Notice tone="err">Nenhum modelo de TTS disponível. Verifique a chave da OpenRouter e o catálogo em Configurações.</Notice>
            )}
            {project.tts?.warning && <Notice tone="amber">{project.tts.warning}</Notice>}
            <div className="font-mono text-[11px] text-muted">
              duração real <span className="text-paper">{minutes(real)}</span> · estimada {minutes(est)} · alvo {project.channel.duration_min}–{project.channel.duration_max} min
            </div>
          </div>
          <div className="flex flex-col items-end gap-2">
            <Btn size="sm" icon={<Music size={11} />} disabled={ready !== scenes.length} loading={merge.isPending} onClick={() => merge.mutate({ gap: 0 })}>
              Gerar narração completa
            </Btn>
            {full && <audio src={full.url} controls preload="none" className="h-8 w-72" />}
          </div>
        </div>
        <div className="border-t border-line">
          {scenes.map((s) => {
            const busy = busyScenes.has(s.id);
            const diff = s.audio_duration ? s.audio_duration - s.est_duration : 0;
            return (
              <div key={s.id} className="grid grid-cols-[52px_1fr] items-center gap-3 border-b border-line py-2.5 last:border-b-0 md:grid-cols-[64px_1fr_300px_120px_auto]">
                <div className="font-mono text-[11px] leading-tight">
                  <div className="text-amber">#{String(s.position).padStart(3, "0")}</div>
                  <div className="tnum text-dim">{timecode(s.start)}</div>
                </div>
                <div className="line-clamp-2 text-[13px] text-paper">{s.narration}</div>
                <div className="col-span-2 md:col-span-1">
                  {s.audio ? <audio src={s.audio.url} controls preload="none" className={clsx("h-8 w-full", !s.audio_ok && "opacity-50")} /> : <span className="font-mono text-[11px] text-dim">sem áudio</span>}
                </div>
                <div className="tnum font-mono text-[11px] text-muted">
                  {s.audio_duration ? (
                    <>
                      {secs(s.audio_duration)} <span className={clsx(Math.abs(diff) > 2 ? "text-amber" : "text-dim")}>({diff >= 0 ? "+" : ""}{diff.toFixed(1)})</span>
                    </>
                  ) : (
                    <span className="text-dim">~{secs(s.est_duration)}</span>
                  )}
                  {s.audio?.cost ? <div className="text-dim">{usd(s.audio.cost)}</div> : null}
                </div>
                <div className="flex items-center gap-2 justify-self-end">
                  <Led status={busy ? "running" : s.audio_ok ? "ok" : s.audio ? "queued" : "off"} />
                  <Btn
                    size="sm"
                    disabled={busy}
                    onClick={() =>
                      void api
                        .post(`/scenes/${s.id}/narration`)
                        .then(() => {
                          toast(`Cena ${s.position}: narração na fila`, "info");
                          invalidate();
                        })
                        .catch((e) => toast(errorMessage(e), "err"))
                    }
                  >
                    {s.audio ? "Renarrar" : "Narrar"}
                  </Btn>
                </div>
              </div>
            );
          })}
        </div>
      </Panel>
    </div>
  );
}
