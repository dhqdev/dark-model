import { useQuery } from "@tanstack/react-query";
import { EstimateTable, StageCostTable } from "../../components/estimate";
import { Loading, Panel } from "../../components/ui";
import { api } from "../../lib/api";
import { tokens, usd } from "../../lib/format";
import type { ProjectDetail, StageCost, Totals } from "../../lib/types";

export function CostsStage({ project }: { project: ProjectDetail }) {
  const { data } = useQuery({
    queryKey: ["project-costs", project.id, project.costs.calls],
    queryFn: () => api.get<{ total: Totals; stages: StageCost[]; models: (Totals & { model: string; operation: string })[] }>(`/projects/${project.id}/costs`),
  });
  return (
    <div className="grid gap-6 2xl:grid-cols-2">
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
