import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { api } from "../lib/api";
import { QUALITY_LABEL, brl, tokens, usd } from "../lib/format";
import type { Estimate, Fx, Quality, StageCost } from "../lib/types";
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

export function fxLabel(fx: Fx): string {
  return `US$ 1 = ${brl(fx.rate)} · ${fx.note}`;
}

export function EstimateTable({ projectId, current }: { projectId: number; current: Quality }) {
  const { data, isLoading } = useEstimate(projectId);
  if (isLoading || !data) return <Loading label="Calculando estimativa" />;
  // linhas alinhadas pela chave (um nível pode ter linhas que outro não tem)
  const keys: string[] = [];
  const labels: Record<string, { label: string; stage: string }> = {};
  for (const t of ["BALANCED", ...TIERS] as Quality[]) {
    for (const l of data.tiers[t].lines) {
      if (!labels[l.key]) {
        keys.push(l.key);
        labels[l.key] = { label: l.label.replace(/\(.*\)/, "").trim(), stage: l.stage };
      }
    }
  }
  const adjusted = TIERS.filter((t) => data.tiers[t].adjustments.length > 0);
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
          <tr className="border-b border-line">
            <td className="py-2 pr-3 text-muted">
              <span className="mr-2 font-mono text-[10px] text-dim uppercase">plano</span>
              Cenas (1 imagem cada)
            </td>
            {TIERS.map((t) => (
              <td key={t} className={clsx("tnum py-2 pl-3 text-right font-mono", t === current && "bg-amber/[0.04]")}>
                {data.tiers[t].scenes}
                {data.tiers[t].plan.scene_seconds ? <span className="text-dim"> · ~{data.tiers[t].plan.scene_seconds}s</span> : null}
              </td>
            ))}
          </tr>
          {keys.map((key) => (
            <tr key={key} className="border-b border-line">
              <td className="py-2 pr-3 text-muted">
                <span className="mr-2 font-mono text-[10px] text-dim uppercase">{labels[key].stage}</span>
                {labels[key].label}
              </td>
              {TIERS.map((t) => {
                const l = data.tiers[t].lines.find((x) => x.key === key);
                return (
                  <td key={t} className={clsx("py-2 pl-3 text-right", t === current && "bg-amber/[0.04]")}>
                    {l ? (
                      <span className="inline-flex items-center gap-2" title={`${l.label}${l.model ? ` · ${l.model}` : ""}${l.tokens_in ? ` · ${tokens(l.tokens_in)} in / ${tokens(l.tokens_out)} out` : ""}`}>
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
                <div className={clsx("tnum font-mono text-[17px]", t === current ? "text-amber" : "text-paper")}>{brl(data.tiers[t].total_brl)}</div>
                <div className="tnum font-mono text-[11.5px] text-dim">{usd(data.tiers[t].total, 2)}</div>
                {!data.tiers[t].complete && <div className="text-[11px] text-signal">+ itens sem preço</div>}
              </td>
            ))}
          </tr>
          <tr>
            <td className="pt-2 pb-1 pr-3 text-[12px] text-muted">Teto por vídeo</td>
            {TIERS.map((t) => {
              const e = data.tiers[t];
              return (
                <td key={t} className={clsx("pt-2 pb-1 pl-3 text-right text-[12px]", t === current && "bg-amber/[0.04]")}>
                  {e.cap_brl ? (
                    <span className={clsx("tnum font-mono", e.fits ? "text-ok" : "text-signal")}>
                      {e.fits ? "✓ " : "✕ "}
                      {brl(e.cap_brl)}
                    </span>
                  ) : (
                    <span className="text-dim">sem teto</span>
                  )}
                </td>
              );
            })}
          </tr>
        </tbody>
      </table>
      {adjusted.length > 0 && (
        <div className="mt-4 space-y-2 border-t border-line pt-3">
          <div className="kicker">Ajustes para caber no teto</div>
          {adjusted.map((t) => (
            <div key={t} className="text-[12.5px]">
              <span className={clsx("mr-2 font-mono text-[10px] tracking-[0.16em] uppercase", t === current ? "text-amber" : "text-dim")}>{QUALITY_LABEL[t]}</span>
              <span className={data.tiers[t].fits === false ? "text-signal" : "text-muted"}>{data.tiers[t].adjustments.join(" · ")}</span>
            </div>
          ))}
        </div>
      )}
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
        Base: {data.inputs.words.toLocaleString("pt-BR")} palavras · ~{data.inputs.minutes.toFixed(1)} min
        {data.inputs.from_target ? " (roteiro vazio: estimado pela duração alvo do canal)" : data.inputs.scenes_planned ? " · cenas reais" : " · cenas estimadas por nível"}.
        {" "}A OpenRouter cobra em dólar; {fxLabel(data.fx)}.
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
