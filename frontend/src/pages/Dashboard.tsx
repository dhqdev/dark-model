import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Plus } from "lucide-react";
import { Link } from "react-router";
import { JobLine } from "../components/jobs";
import { Badge, Empty, ErrorBox, Loading, Notice, PageHeader, Panel, Stat } from "../components/ui";
import { api } from "../lib/api";
import { PROJECT_STATUS, QUALITY_LABEL, relative, tokens, usd } from "../lib/format";
import type { Balance, Dashboard as DashboardData } from "../lib/types";

export function Dashboard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api.get<DashboardData>("/dashboard"),
    refetchInterval: (q) => ((q.state.data?.queue.running ?? 0) + (q.state.data?.queue.queued ?? 0) > 0 ? 3000 : 15000),
  });
  const balance = useQuery({
    queryKey: ["balance"],
    queryFn: () => api.get<Balance>("/usage/balance"),
    enabled: !!data?.openrouter_configured,
    refetchInterval: 120_000,
  });

  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorBox error={error} />;

  return (
    <div>
      <PageHeader
        kicker="01 / Console"
        title={
          <>
            Mesa de <em className="text-amber">produção</em>
          </>
        }
        subtitle="Visão geral dos canais, projetos em andamento, fila de geração e consumo real na OpenRouter."
        actions={
          <Link className="btn btn-primary" to="/canais">
            <Plus size={13} /> Novo projeto
          </Link>
        }
      />

      {!data.openrouter_configured && (
        <div className="mb-6">
          <Notice tone="amber">
            A chave da OpenRouter não está configurada. Defina <code className="font-mono text-amber">OPENROUTER_API_KEY</code> na Stack do Portainer e
            reinicie o serviço.
          </Notice>
        </div>
      )}
      {data.workers.length === 0 && (
        <div className="mb-6">
          <Notice tone="err">
            Nenhum worker online — as tarefas ficam na fila até um worker iniciar (serviço <code className="font-mono">worker</code> da Stack).
          </Notice>
        </div>
      )}

      <div className="panel mb-8 grid grid-cols-2 divide-line md:grid-cols-4 xl:grid-cols-7 [&>*]:border-line [&>*]:border-b xl:[&>*]:border-b-0 [&>*:not(:last-child)]:border-r">
        <Stat label="Canais" value={data.counts.channels} />
        <Stat label="Projetos" value={data.counts.projects} sub={`${data.counts.projects_by_status.exported ?? 0} exportados`} />
        <Stat label="Fila" value={`${data.queue.running} / ${data.queue.queued}`} sub="rodando / aguardando" />
        <Stat label="Custo hoje" value={usd(data.costs.today.cost, 2)} sub={`${tokens(data.costs.today.tokens)} tokens`} />
        <Stat label="Custo no mês" value={usd(data.costs.month.cost, 2)} sub={`${data.costs.month.calls} chamadas`} />
        <Stat label="Custo total" value={usd(data.costs.total.cost, 2)} sub={`${tokens(data.costs.total.tokens)} tokens`} />
        <Stat
          accent
          label="Saldo"
          value={balance.data?.available ? usd(balance.data.balance, 2) : "—"}
          sub={balance.data?.available ? (balance.data.source === "credits" ? "OpenRouter · créditos" : "OpenRouter · limite da chave") : "OpenRouter · ver Consumo"}
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
        <Panel
          index="A"
          title="Projetos recentes"
          actions={
            <Link to="/canais" className="btn btn-sm">
              Canais <ArrowRight size={11} />
            </Link>
          }
          bodyClass="p-0"
        >
          {data.recent_projects.length === 0 ? (
            <div className="p-4">
              <Empty title="Nenhum projeto ainda" text="Crie um canal, defina a Skill e comece o primeiro projeto." action={<Link className="btn btn-primary" to="/canais">Criar canal</Link>} />
            </div>
          ) : (
            <div>
              {data.recent_projects.map((p) => (
                <Link key={p.id} to={`/projetos/${p.id}`} className="grid grid-cols-1 items-center gap-2 border-b border-line px-4 py-3 last:border-b-0 hover:bg-raised sm:grid-cols-[1fr_auto] sm:gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-[14.5px] text-paper">{p.selected_title || p.title}</div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[12px] text-dim">
                      <span className="text-muted">{p.channel_name}</span>
                      <span>·</span>
                      <span>{p.scenes ?? 0} cenas</span>
                      <span>·</span>
                      <span>{relative(p.updated_at)}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge tone="dim">{QUALITY_LABEL[p.quality]}</Badge>
                    <Badge tone={p.status === "exported" ? "ok" : "default"}>{PROJECT_STATUS[p.status] ?? p.status}</Badge>
                    <span className="tnum w-16 text-right font-mono text-[12px] text-muted">{usd(p.cost)}</span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </Panel>

        <div className="space-y-6">
          <Panel index="B" title="Em produção agora" actions={<Link to="/fila" className="btn btn-sm">Fila <ArrowRight size={11} /></Link>}>
            {data.active_jobs.length === 0 ? (
              <div className="py-4 text-[13px] text-dim">Nenhuma tarefa rodando.</div>
            ) : (
              data.active_jobs.map((j) => <JobLine key={j.id} job={j} showProject compact />)
            )}
          </Panel>
          <Panel index="C" title="Falhas recentes">
            {data.recent_failures.length === 0 ? (
              <div className="py-4 text-[13px] text-dim">Sem falhas nas últimas 48 horas.</div>
            ) : (
              data.recent_failures.map((j) => <JobLine key={j.id} job={j} showProject compact />)
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
