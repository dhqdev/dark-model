import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { DailyChart } from "../components/DailyChart";
import { StageCostTable } from "../components/estimate";
import { Btn, ErrorBox, Loading, Notice, PageHeader, Panel, Segmented, Stat } from "../components/ui";
import { api } from "../lib/api";
import { tokens, usd } from "../lib/format";
import type { Balance, UsageSummary } from "../lib/types";

export function Usage() {
  const [view, setView] = useState<"chart" | "table">("chart");
  const { data, isLoading, error } = useQuery({ queryKey: ["usage"], queryFn: () => api.get<UsageSummary>("/usage/summary"), refetchInterval: 30_000 });
  const balance = useQuery({ queryKey: ["balance"], queryFn: () => api.get<Balance>("/usage/balance") });
  const refresh = useQuery({ queryKey: ["balance-refresh"], queryFn: () => api.get<Balance>("/usage/balance?refresh=1"), enabled: false });

  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorBox error={error} />;
  const b = refresh.data ?? balance.data;

  return (
    <div>
      <PageHeader kicker="04 / Consumo" title="Consumo e custos" subtitle="Custos reais informados pela OpenRouter em cada geração — por etapa, projeto, canal e modelo." />
      <div className="mb-6 grid items-start gap-6 xl:grid-cols-[minmax(300px,0.8fr)_2fr]">
        <Panel
          index="$"
          title="Saldo OpenRouter"
          actions={
            <Btn size="sm" icon={<RefreshCw size={11} />} loading={refresh.isFetching} onClick={() => void refresh.refetch()}>
              Atualizar
            </Btn>
          }
        >
          <div className="text-[52px] leading-none font-semibold tracking-tight text-paper">{b?.available ? usd(b.balance, 2) : "—"}</div>
          <div className="mt-2 text-[12.5px] text-muted">
            {b?.available
              ? b.source === "credits"
                ? `Créditos da conta: ${usd(b.credits?.total_credits ?? null, 2)} comprados · ${usd(b.credits?.total_usage ?? null, 2)} usados`
                : "Limite restante da chave de API (a OpenRouter só informa o saldo da conta com chave de gerenciamento)."
              : b?.reason}
          </div>
          {b?.key && (
            <div className="mt-4 grid grid-cols-3 gap-px border border-line bg-line font-mono text-[11px]">
              {(
                [
                  ["Hoje", b.key.usage_daily],
                  ["Mês", b.key.usage_monthly],
                  ["Total", b.key.usage],
                ] as [string, unknown][]
              ).map(([k, v]) => (
                <div key={k} className="bg-panel px-3 py-2">
                  <div className="kicker">{k} na chave</div>
                  <div className="tnum mt-1 text-paper">{typeof v === "number" ? usd(v, 2) : "—"}</div>
                </div>
              ))}
            </div>
          )}
        </Panel>
        <div className="panel grid grid-cols-2 md:grid-cols-4 [&>*:not(:last-child)]:border-r [&>*]:border-line">
          <Stat label="Hoje" value={usd(data.today.cost, 2)} sub={`${tokens(data.today.tokens)} tokens · ${data.today.calls} chamadas`} />
          <Stat label="Últimos 7 dias" value={usd(data.last_7_days.cost, 2)} sub={`${tokens(data.last_7_days.tokens)} tokens`} />
          <Stat label="Mês" value={usd(data.month.cost, 2)} sub={`${tokens(data.month.tokens)} tokens`} />
          <Stat label="Total" value={usd(data.total.cost, 2)} sub={`${data.total.pending ? `${data.total.pending} aguardando confirmação` : `${data.total.calls} chamadas`}`} accent />
        </div>
      </div>

      <div className="mb-6">
        {data.budget.daily_limit_usd || data.budget.project_limit_usd ? (
          <Notice tone="info">
            Limites de gasto ativos: {data.budget.daily_limit_usd ? `diário ${usd(data.budget.daily_limit_usd, 2)}` : "sem limite diário"} ·{" "}
            {data.budget.project_limit_usd ? `por projeto ${usd(data.budget.project_limit_usd, 2)}` : "sem limite por projeto"} —{" "}
            <Link to="/ajustes" className="text-amber hover:underline">
              alterar
            </Link>
          </Notice>
        ) : (
          <Notice tone="amber">
            Nenhum limite de gasto definido.{" "}
            <Link to="/ajustes" className="text-amber hover:underline">
              Defina um limite diário e por projeto
            </Link>{" "}
            para que o sistema pare novas gerações automaticamente ao atingi-lo.
          </Notice>
        )}
      </div>

      <Panel index="A" title="Custo por dia · últimos 30 dias" className="mb-6" actions={<Segmented value={view} onChange={setView} options={[{ value: "chart", label: "Gráfico" }, { value: "table", label: "Tabela" }]} />}>
        {view === "chart" ? (
          <DailyChart days={data.days} />
        ) : (
          <div className="grid grid-cols-2 gap-x-8 font-mono text-[12px] sm:grid-cols-3 lg:grid-cols-5">
            {data.days.length === 0 && <div className="text-dim">Sem consumo no período.</div>}
            {data.days.map((d) => (
              <div key={d.day} className="flex justify-between border-b border-line py-1.5">
                <span className="text-muted">{d.day.slice(5, 10).split("-").reverse().join("/")}</span>
                <span className="tnum text-paper">{usd(d.cost)}</span>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <div className="grid items-start gap-6 xl:grid-cols-2">
        <Panel index="B" title="Por etapa">
          <StageCostTable stages={data.stages} />
        </Panel>
        <Panel index="C" title="Por canal" bodyClass="p-0">
          {data.channels.length === 0 && <div className="px-4 py-6 text-[13px] text-dim">Sem consumo ainda.</div>}
          {data.channels.map((c) => (
            <div key={c.channel_id ?? "none"} className="grid grid-cols-[1fr_auto_auto] gap-4 border-b border-line px-4 py-2.5 text-[13px] last:border-b-0">
              {c.channel_id ? (
                <Link to={`/canais/${c.channel_id}`} className="truncate hover:text-amber">
                  {c.name}
                </Link>
              ) : (
                <span className="text-dim">Sem canal</span>
              )}
              <span className="tnum font-mono text-[12px] text-muted">{tokens(c.tokens)} tok</span>
              <span className="tnum font-mono text-[12px] text-paper">{usd(c.cost)}</span>
            </div>
          ))}
        </Panel>
        <Panel index="D" title="Por projeto" bodyClass="p-0">
          {data.projects.length === 0 && <div className="px-4 py-6 text-[13px] text-dim">Sem consumo ainda.</div>}
          {data.projects.map((p) => (
            <div key={p.project_id} className="grid grid-cols-[1fr_auto_auto] gap-4 border-b border-line px-4 py-2.5 text-[13px] last:border-b-0">
              <Link to={`/projetos/${p.project_id}`} className="truncate hover:text-amber">
                {p.title}
              </Link>
              <span className="tnum font-mono text-[12px] text-muted">{tokens(p.tokens)} tok</span>
              <span className="tnum font-mono text-[12px] text-paper">{usd(p.cost)}</span>
            </div>
          ))}
        </Panel>
        <Panel index="E" title="Por modelo" bodyClass="p-0">
          {data.models.length === 0 && <div className="px-4 py-6 text-[13px] text-dim">Sem consumo ainda.</div>}
          {data.models.map((m) => (
            <div key={`${m.model}-${m.operation}`} className="grid grid-cols-[1fr_auto_auto] gap-4 border-b border-line px-4 py-2.5 text-[13px] last:border-b-0">
              <span className="truncate">
                <span className="mr-2 font-mono text-[10px] text-dim uppercase">{m.operation}</span>
                {m.model}
              </span>
              <span className="tnum font-mono text-[12px] text-muted">{m.calls}×</span>
              <span className="tnum font-mono text-[12px] text-paper">{usd(m.cost)}</span>
            </div>
          ))}
        </Panel>
      </div>
    </div>
  );
}
