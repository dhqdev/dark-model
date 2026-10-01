import { Clapperboard, Download, RefreshCw } from "lucide-react";
import { Btn, Empty, Led, Notice, Panel } from "../../components/ui";
import { bytes, dateTime, timecode } from "../../lib/format";
import type { ProjectDetail } from "../../lib/types";
import { useProjectAction } from "./shared";

export function VideoStage({ project }: { project: ProjectDetail }) {
  const r = project.stages.render;
  const run = useProjectAction(project.id, "render", "Montagem do vídeo final na fila");
  const busy = r.running || run.isPending;
  const job = project.active_jobs.find((j) => j.kind === "render.final");
  const st = project.stages;

  if (!st.scenes.count) return <Empty title="Crie as cenas primeiro" text="O vídeo final junta as imagens/vídeos das cenas com a narração." />;

  const checks: [string, boolean, string][] = [
    ["Imagens das cenas", r.missing_images.length === 0, r.missing_images.length ? `faltam: ${r.missing_images.slice(0, 12).join(", ")}` : `${st.visuals.total} cenas`],
    ["Narração das cenas", r.missing_audio.length === 0, r.missing_audio.length ? `faltam: ${r.missing_audio.slice(0, 12).join(", ")}` : timecode(st.narration.duration)],
    ["Clipes (movimento / vídeo IA)", r.complete, r.complete ? "prontos" : "os que faltarem são feitos na montagem"],
  ];

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
      <Panel
        index="05"
        title="Vídeo final"
        actions={
          r.last ? (
            <a className="btn btn-primary btn-sm" href={`${r.last.url}?download=1`} download>
              <Download size={12} /> Baixar MP4
            </a>
          ) : undefined
        }
      >
        {r.last ? (
          <div className="space-y-3">
            <video key={r.last.id} src={r.last.url} controls preload="metadata" className="aspect-video w-full border border-line bg-coal" />
            <div className="flex flex-wrap gap-x-5 gap-y-1 font-mono text-[11.5px] text-muted">
              <span>
                duração <span className="text-paper">{timecode(r.last.duration)}</span>
              </span>
              <span>
                {r.last.width}×{r.last.height} · {bytes(r.last.size)}
              </span>
              {r.info && (
                <span>
                  {r.info.transitions} transições · {r.info.overlays} textos · {r.info.sfx} efeitos sonoros
                </span>
              )}
              <span>
                {r.info?.auto ? "montado automaticamente" : "montado"} em {dateTime(r.last.created_at)}
              </span>
            </div>
            {r.outdated && <Notice tone="amber">As cenas mudaram depois desta montagem (imagem, narração, transição, efeito ou texto). Monte de novo para atualizar.</Notice>}
            {r.info?.warnings && r.info.warnings.length > 0 && (
              <Notice tone="amber">
                {r.info.warnings.slice(0, 6).map((w) => (
                  <div key={w}>{w}</div>
                ))}
              </Notice>
            )}
          </div>
        ) : busy ? (
          <div className="flex aspect-video w-full flex-col items-center justify-center gap-2 border border-line bg-coal">
            <span className="font-mono text-[11px] tracking-[0.3em] text-amber uppercase">Montando</span>
            <span className="font-mono text-[11px] text-dim">{job ? `${Math.round(job.progress * 100)}% · ${job.message}` : "na fila"}</span>
          </div>
        ) : (
          <div className="flex aspect-video w-full flex-col items-center justify-center gap-2 border border-line bg-coal">
            <span className="font-mono text-[11px] tracking-[0.3em] text-dim uppercase">Sem vídeo</span>
            <span className="max-w-md text-center text-[12.5px] text-dim">Monta sozinho quando a narração e os visuais terminam — ou clique em “Montar vídeo”.</span>
          </div>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          <Btn variant={r.last ? "ghost" : "primary"} icon={r.last ? <RefreshCw size={12} /> : <Clapperboard size={12} />} loading={busy} disabled={!r.can_render} onClick={() => run.mutate(undefined)}>
            {r.last ? "Montar de novo" : "Montar vídeo"}
          </Btn>
        </div>
      </Panel>

      <div className="space-y-6">
        <Panel title="Antes de montar">
          <div className="space-y-2">
            {checks.map(([label, ok, detail]) => (
              <div key={label} className="flex items-center justify-between gap-3 border-b border-line py-2 last:border-b-0">
                <span className="flex items-center gap-3 text-[13.5px]">
                  <Led status={ok ? "ok" : "queued"} /> {label}
                </span>
                <span className="max-w-[55%] truncate font-mono text-[11px] text-muted">{detail}</span>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="Como é montado">
          <ul className="space-y-2 text-[12.5px] text-muted">
            <li>
              <span className="text-paper">Sem IA e sem custo:</span> o servidor junta tudo com o ffmpeg.
            </li>
            <li>
              <span className="text-paper">Transições</span> entre as cenas (dissolver, fade preto, flash, deslizar, zoom, desfoque, círculo) — escolhidas pela IA ao planejar as cenas e editáveis em cada cena.
            </li>
            <li>
              <span className="text-paper">Texto na tela</span> com efeito de máquina de escrever, só nas cenas em que combina (datas, lugares, nomes, números).
            </li>
            <li>
              <span className="text-paper">Efeitos sonoros</span> (whoosh, impacto, subida, tensão, batimento, vento, estrondo, relógio) gerados no próprio servidor — sem direitos autorais de terceiros.
            </li>
            <li>
              <span className="text-paper">Cenas longas</span> ganham um segundo enquadramento no meio; vídeo IA mais curto que a narração continua com movimento suave do último quadro.
            </li>
          </ul>
        </Panel>
      </div>
    </div>
  );
}
