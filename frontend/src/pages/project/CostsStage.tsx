import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { EstimateTable, StageCostTable, useEstimate } from "../../components/estimate";
import { Loading, Panel } from "../../components/ui";
import { api } from "../../lib/api";
import { QUALITY_LABEL, brl, tokens, usd } from "../../lib/format";
import type { Estimate, ProjectDetail, StageCost, Totals } from "../../lib/types";

const STAGE_LABEL: Record<string, string> = {
  script: "Roteiro",
  scenes: "Cenas",
  visuals: "Imagens/Vídeos",
  narration: "Narração",
  thumbnail: "Thumbnail",
  metadata: "Título e descrição",
  learning: "Skill / aprendizado",
};

/** Plano do nível atual × o que a OpenRouter cobrou de verdade, etapa por etapa. */
function PlanVsReal({ project, estimate, stages }: { project: ProjectDetail; estimate: Estimate; stages: StageCost[] }) {
  const tier = estimate.tiers[project.quality];
  const rate = estimate.fx.rate;
  const planned: Record<string, number> = {};
  for (const ln of tier.lines) planned[ln.stage] = (planned[ln.stage] ?? 0) + (ln.cost ?? 0);
  const real: Record<string, number> = {};
  for (const st of stages) real[st.stage] = st.cost;
  const keys = Object.keys(STAGE_LABEL).filter((k) => (planned[k] ?? 0) > 0 || (real[k] ?? 0) > 0);
  const totalPlan = keys.reduce((s, k) => s + (planned[k] ?? 0), 0);
  const totalReal = keys.reduce((s, k) => s + (real[k] ?? 0), 0);
  const diff = (p: number, r: number) => (p > 0 && r > 0 ? Math.round(((r - p) / p) * 100) : null);
  const row = (label: string, p: number, r: number, strong = false) => {
    const d = diff(p, r);
    return (
      <tr key={label} className={clsx(!strong && "border-b border-line")}>
        <td className={clsx("py-2", strong ? "pt-3 font-mono text-[11px] tracking-[0.16em] uppercase" : "text-muted")}>{label}</td>
        <td className="tnum py-2 text-right font-mono">{brl(p * rate)}</td>
        <td className={clsx("tnum py-2 text-right font-mono", strong ? "text-[16px] text-amber" : "text-paper")}>{r > 0 ? brl(r * rate) : "—"}</td>
        <td className={clsx("tnum py-2 text-right font-mono", d === null ? "text-dim" : d > 15 ? "text-signal" : d < -15 ? "text-ok" : "text-muted")}>
          {d === null ? "—" : `${d > 0 ? "+" : ""}${d}%`}
        </td>
      </tr>
    );
  };
  return (
    <>
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr className="border-b border-edge">
            <th className="kicker py-2 text-left font-normal">Etapa</th>
            <th className="kicker py-2 text-right font-normal">Planejado</th>
            <th className="kicker py-2 text-right font-normal">Real</th>
            <th className="kicker py-2 text-right font-normal">Diferença</th>
          </tr>
        </thead>
        <tbody>
          {keys.map((k) => row(STAGE_LABEL[k], planned[k] ?? 0, real[k] ?? 0))}
          {row("Total", totalPlan, totalReal, true)}
        </tbody>
      </table>
      <div className="mt-3 text-[11.5px] text-dim">
        Plano {QUALITY_LABEL[project.quality]} ({usd(tier.total, 2)}
        {tier.cap_brl ? ` · teto ${brl(tier.cap_brl)}` : ""}). Compare só etapas já concluídas: “—” no real = ainda não gerado. Real bem acima do
        planejado costuma ser refação (imagens, narração ou cenas geradas de novo); a estimativa aprende com os seus custos reais (◆).
      </div>
    </>
  );
}

export function CostsStage({ project }: { project: ProjectDetail }) {
  const { data } = useQuery({
    queryKey: ["project-costs", project.id, project.costs.calls],
    queryFn: () => api.get<{ total: Totals; stages: StageCost[]; models: (Totals & { model: string; operation: string })[] }>(`/projects/${project.id}/costs`),
  });
  const estimate = useEstimate(project.id);
  return (
    <div className="grid gap-6 2xl:grid-cols-2">
      {estimate.data && data && project.costs.cost > 0 && (
        <Panel index="$" title="Planejado × real" className="2xl:col-span-2">
          <PlanVsReal project={project} estimate={estimate.data} stages={data.stages} />
        </Panel>
      )}
      <Panel index="$" title="Estimativa antes de gerar · 3 níveis">
        <EstimateTable projectId={project.id} current={project.quality} />
      </Panel>
      <div className="space-y-6">
        <Panel index="$" title="Custo real por etapa">
          {!data ? <Loading /> : <StageCostTable stages={data.stages} />}
          <div className="mt-3 text-[11.5px] text-dim">
            Valores informados pela OpenRouter em cada resposta (campo usage.cost) ou consultados em /generation. * = aguardando confirmação.
          </div>
        </Panel>
        <Panel title="Por modelo" bodyClass="p-0">
          {(data?.models ?? []).map((m) => (
            <div key={`${m.model}-${m.operation}`} className="grid grid-cols-[1fr_auto_auto] gap-4 border-b border-line px-4 py-2.5 text-[13px] last:border-b-0">
              <span className="truncate">
                <span className="mr-2 font-mono text-[10px] text-dim uppercase">{m.operation}</span>
                {m.model}
              </span>
              <span className="tnum font-mono text-[12px] text-muted">{tokens(m.tokens)} tok · {m.calls}×</span>
              <span className="tnum font-mono text-[12px] text-paper">{usd(m.cost)}</span>
            </div>
          ))}
          {data && data.models.length === 0 && <div className="px-4 py-6 text-[13px] text-dim">Nada gerado ainda.</div>}
        </Panel>
      </div>
    </div>
  );
}
