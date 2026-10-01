import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { api } from "../lib/api";
import { QUALITY_LABEL, tokens, usd } from "../lib/format";
import type { Estimate, Quality, StageCost } from "../lib/types";
import { Loading, SourceMark } from "./ui";

const TIERS: Quality[] = ["ECONOMY", "BALANCED", "PREMIUM"];

export function useEstimate(projectId: number, enabled = true) {
  return useQuery({
    queryKey: ["estimate", projectId],
    queryFn: () => api.get<Estimate>(`/projects/${projectId}/estimate`),
    enabled,
    staleTime: 30_000,
  });
}

export function EstimateTable({ projectId, current }: { projectId: number; current: Quality }) {
  const { data, isLoading } = useEstimate(projectId);
  if (isLoading || !data) return <Loading label="Calculando estimativa" />;
  const lines = data.tiers.BALANCED.lines.map((l, i) => ({ key: i, label: l.label.replace(/\(.*\)/, "").trim(), stage: l.stage }));
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] border-collapse text-[13px]">
        <thead>
          <tr className="border-b border-edge">
            <th className="kicker py-2 pr-3 text-left font-normal">Etapa</th>
            {TIERS.map((t) => (
              <th key={t} className={clsx("kicker py-2 pl-3 text-right font-normal", t === current && "text-amber")}>
                {QUALITY_LABEL[t]}
                {t === current ? " ◀" : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {lines.map((row) => (
            <tr key={row.key} className="border-b border-line">
              <td className="py-2 pr-3 text-muted">
                <span className="mr-2 font-mono text-[10px] text-dim uppercase">{row.stage}</span>
                {row.label}
              </td>
              {TIERS.map((t) => {
                const l = data.tiers[t].lines[row.key];
                return (
                  <td key={t} className={clsx("py-2 pl-3 text-right", t === current && "bg-amber/[0.04]")}>
                    {l ? (
                      <span className="inline-flex items-center gap-2" title={`${l.model ?? ""}${l.tokens_in ? ` · ${tokens(l.tokens_in)} in / ${tokens(l.tokens_out)} out` : ""}`}>
                        <span className="tnum font-mono">{usd(l.cost)}</span>
                        <SourceMark source={l.source} note={l.note} />
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
          <tr>
            <td className="pt-3 pr-3 font-mono text-[11px] tracking-[0.16em] text-paper uppercase">Total estimado</td>
            {TIERS.map((t) => (
              <td key={t} className={clsx("pt-3 pl-3 text-right", t === current && "bg-amber/[0.04]")}>
                <span className={clsx("tnum font-mono text-[17px]", t === current ? "text-amber" : "text-paper")}>{usd(data.tiers[t].total, 2)}</span>
                {!data.tiers[t].complete && <div className="text-[11px] text-signal">+ itens sem preço</div>}
              </td>
            ))}
          </tr>
        </tbody>
      </table>
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[11.5px] text-dim">
        <span>
          <SourceMark source="live" /> preço do catálogo OpenRouter
        </span>
        <span>
          <SourceMark source="history" /> média dos seus custos reais
        </span>
        <span>
          <SourceMark source="heuristic" /> preço real, quantidade aproximada
        </span>
        <span>
          <SourceMark source="free" /> local, sem custo
        </span>
        <span>
          <SourceMark source="unavailable" /> sem preço publicado
        </span>
      </div>
      <div className="mt-2 text-[11.5px] text-dim">
        Base: {data.inputs.words.toLocaleString("pt-BR")} palavras · ~{data.inputs.minutes.toFixed(1)} min · {data.inputs.scenes} cenas
        {data.inputs.from_target ? " (roteiro vazio: estimado pela duração alvo do canal)" : data.inputs.scenes_planned ? " (cenas reais)" : " (cenas estimadas)"}.
      </div>
    </div>
  );
}

export function StageCostTable({ stages }: { stages: StageCost[] }) {
  const total = stages.reduce((s, x) => s + x.cost, 0);
  return (
    <table className="w-full border-collapse text-[13px]">
      <thead>
        <tr className="border-b border-edge">
          <th className="kicker py-2 text-left font-normal">Etapa</th>
          <th className="kicker py-2 text-right font-normal">Tokens in</th>
          <th className="kicker py-2 text-right font-normal">Tokens out</th>
          <th className="kicker py-2 text-right font-normal">Chamadas</th>
          <th className="kicker py-2 text-right font-normal">Custo real</th>
        </tr>
      </thead>
      <tbody>
        {stages.map((s) => (
          <tr key={s.stage} className="border-b border-line">
            <td className="py-2 text-muted">{s.label}</td>
            <td className="tnum py-2 text-right font-mono">{tokens(s.tokens_in)}</td>
            <td className="tnum py-2 text-right font-mono">{tokens(s.tokens_out)}</td>
            <td className="tnum py-2 text-right font-mono">{s.calls}</td>
            <td className="tnum py-2 text-right font-mono text-paper">
              {usd(s.cost)}
              {s.pending > 0 && (
                <span className="ml-1 text-amber" title={`${s.pending} custo(s) aguardando confirmação da OpenRouter`}>
                  *
                </span>
              )}
            </td>
          </tr>
        ))}
        <tr>
          <td className="pt-3 font-mono text-[11px] tracking-[0.16em] uppercase">Total</td>
          <td className="tnum pt-3 text-right font-mono">{tokens(stages.reduce((s, x) => s + x.tokens_in, 0))}</td>
          <td className="tnum pt-3 text-right font-mono">{tokens(stages.reduce((s, x) => s + x.tokens_out, 0))}</td>
          <td className="tnum pt-3 text-right font-mono">{stages.reduce((s, x) => s + x.calls, 0)}</td>
          <td className="tnum pt-3 text-right font-mono text-[16px] text-amber">{usd(total)}</td>
        </tr>
      </tbody>
    </table>
  );
}
