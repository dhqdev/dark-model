import { useQuery } from "@tanstack/react-query";
import { Download, GraduationCap, Package } from "lucide-react";
import { useState } from "react";
import { Btn, Field, Led, Notice, Panel } from "../../components/ui";
import { api } from "../../lib/api";
import { bytes, dateTime } from "../../lib/format";
import type { Asset, ProjectDetail } from "../../lib/types";
import { useProjectAction } from "./shared";

export function ExportStage({ project }: { project: ProjectDetail }) {
  const [includeClips, setIncludeClips] = useState(true);
  const [gap, setGap] = useState(0);
  const run = useProjectAction<{ include_clips: boolean; gap: number }>(project.id, "export", "Exportação na fila");
  const learn = useProjectAction(project.id, "learn", "Extraindo aprendizados para a Skill");
  const exports = useQuery({
    queryKey: ["exports", project.id, project.stages.export.count],
    queryFn: () => api.get<Asset[]>(`/projects/${project.id}/exports`),
  });
  const st = project.stages;
  const checks: [string, boolean, string][] = [
    ["Roteiro analisado", st.script.analysis_fresh, st.script.analyzed ? (st.script.analysis_fresh ? "ok" : "análise desatualizada") : "sem análise"],
    ["Cenas criadas", st.scenes.count > 0, `${st.scenes.count} cenas`],
    ["Visuais prontos", st.visuals.total > 0 && st.visuals.ready === st.visuals.total, `${st.visuals.ready}/${st.visuals.total}`],
    ["Narração pronta", st.narration.total > 0 && st.narration.ready === st.narration.total, `${st.narration.ready}/${st.narration.total}`],
    ["Thumbnail escolhida", st.thumbnail.selected, `${st.thumbnail.concepts} conceitos`],
    ["Título definido", !!project.selected_title, project.selected_title || "—"],
  ];
  const running = project.active_jobs.some((j) => j.kind === "export.zip");
  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_1fr]">
      <Panel index="08" title="Exportação para edição">
        <div className="space-y-2">
          {checks.map(([label, ok, detail]) => (
            <div key={label} className="flex items-center justify-between border-b border-line py-2 last:border-b-0">
              <span className="flex items-center gap-3 text-[13.5px]">
                <Led status={ok ? "ok" : "queued"} /> {label}
              </span>
              <span className="max-w-[55%] truncate font-mono text-[11px] text-muted">{detail}</span>
            </div>
          ))}
        </div>
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <label className="flex items-center gap-3 text-[13px] text-muted">
            <input type="checkbox" className="accent-amber" checked={includeClips} onChange={(e) => setIncludeClips(e.target.checked)} />
            Incluir clipes de vídeo/motion (MP4)
          </label>
          <Field label="Pausa entre cenas (s)">
            <input className="input tnum" type="number" min={0} max={3} step={0.1} value={gap} onChange={(e) => setGap(Number(e.target.value))} />
          </Field>
        </div>
        <div className="mt-5 flex flex-wrap gap-2">
          <Btn variant="primary" icon={<Package size={13} />} loading={run.isPending || running} onClick={() => run.mutate({ include_clips: includeClips, gap })}>
            Gerar pacote ZIP
          </Btn>
          <Btn icon={<GraduationCap size={13} />} loading={learn.isPending} onClick={() => learn.mutate(undefined)} title="A IA lê suas escolhas e edições neste projeto e propõe regras para a Skill do canal">
            Extrair aprendizados
          </Btn>
        </div>
        {st.export.outdated && (
          <div className="mt-4">
            <Notice tone="amber">Há arquivos mais novos que o último pacote. Gere um novo ZIP para incluí-los.</Notice>
          </div>
        )}
        <div className="mt-6">
          <div className="label">Pacotes gerados</div>
          {(exports.data ?? []).length === 0 && <div className="text-[13px] text-dim">Nenhum pacote ainda.</div>}
          {(exports.data ?? []).map((a) => {
            const warnings = (a.params.warnings as string[] | undefined) ?? [];
            return (
              <div key={a.id} className="flex items-center justify-between gap-3 border-b border-line py-2.5 last:border-b-0">
                <div className="min-w-0">
                  <div className="truncate font-mono text-[12px] text-paper">{a.url.split("/").slice(-2, -1)[0] && `pacote #${a.id}`}</div>
                  <div className="font-mono text-[11px] text-dim">
                    {dateTime(a.created_at)} · {bytes(a.size)}
                    {warnings.length ? <span className="text-amber"> · {warnings.length} avisos</span> : null}
                  </div>
                </div>
                <a className="btn btn-sm" href={`${a.url}?download=1`} download>
                  <Download size={11} /> Baixar
                </a>
              </div>
            );
          })}
        </div>
      </Panel>
      <Panel title="Estrutura do pacote">
        <pre className="overflow-x-auto font-mono text-[12px] leading-relaxed text-muted">{`projeto/
├── LEIA-ME.txt            instruções de montagem
├── timeline.json          linha do tempo (montagem automática futura)
├── projeto.json           dados completos + custos
├── 01_roteiro/            roteiro.txt · analise.md · analise.json
├── 02_cenas/              cenas.csv · cenas.json (tempos, prompts)
├── 03_visuais/            cena_001.mp4|jpg … (ordem da timeline)
│   └── imagens/           imagens-base 1920×1080
├── 04_narracao/           cena_001.mp3 … narracao_completa.mp3
├── 05_legendas/           legendas.srt (sincronizadas)
├── 06_thumbnail/          thumb_01_v1_ESCOLHIDA.jpg …
└── 07_metadados/          titulo · descricao · tags · capitulos`}</pre>
        <div className="mt-4 space-y-2 text-[13px] text-muted">
          <p>
            <span className="text-paper">No CapCut:</span> importe a narração completa, depois todos os arquivos de <code className="font-mono text-amber">03_visuais</code> em
            sequência — já estão ordenados e cortados na duração de cada cena. Importe as legendas SRT em Texto → Legendas.
          </p>
          <p>
            O <code className="font-mono text-amber">timeline.json</code> descreve trilhas de vídeo, narração, legendas, música e efeitos — a base para a futura montagem
            automática.
          </p>
        </div>
      </Panel>
    </div>
  );
}
