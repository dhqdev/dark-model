import { useMemo, useState } from "react";
import { usd } from "../lib/format";

// Cor da série validada (dataviz validate_palette) contra a superfície #14120e: faixa L, croma e contraste OK.
const SERIES = "#c98226";
const SERIES_HOVER = "#f0a43a";
const GRID = "#29251f";

/** Escala com marcas "redondas": passo 1/2/2,5/5 × 10^k e topo múltiplo do passo. */
function niceScale(v: number, target = 4): { max: number; step: number } {
  if (v <= 0) return { max: 1, step: 0.25 };
  const raw = v / target;
  const exp = Math.pow(10, Math.floor(Math.log10(raw)));
  const n = raw / exp;
  const step = (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * exp;
  return { max: Math.ceil(v / step) * step, step };
}

function shortDay(iso: string): string {
  const [, m, d] = iso.split("-");
  return `${d}/${m}`;
}

/** Custo diário (série única): colunas finas, base quadrada, ponta arredondada, tooltip por coluna. */
export function DailyChart({ days }: { days: { day: string; cost: number }[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const series = useMemo(() => {
    const byDay = new Map(days.map((d) => [d.day.slice(0, 10), d.cost]));
    const out: { day: string; cost: number }[] = [];
    const today = new Date();
    for (let i = 29; i >= 0; i--) {
      const dt = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - i));
      const key = dt.toISOString().slice(0, 10);
      out.push({ day: key, cost: byDay.get(key) ?? 0 });
    }
    return out;
  }, [days]);

  const W = 900;
  const H = 240;
  const pad = { l: 56, r: 12, t: 18, b: 26 };
  const innerW = W - pad.l - pad.r;
  const innerH = H - pad.t - pad.b;
  const { max, step } = niceScale(Math.max(...series.map((d) => d.cost)));
  const ticks = Array.from({ length: Math.round(max / step) + 1 }, (_, i) => i * step);
  const tickDigits = step >= 1 ? 0 : step >= 0.1 ? 2 : 3;
  const slot = innerW / series.length;
  const barW = Math.min(24, slot - 2);
  const peak = series.reduce((best, d, i) => (d.cost > series[best].cost ? i : best), 0);
  const y = (v: number) => pad.t + innerH - (v / max) * innerH;

  function barPath(x: number, top: number, w: number): string {
    const h = pad.t + innerH - top;
    if (h <= 0) return "";
    const r = Math.min(4, w / 2, h);
    const base = pad.t + innerH;
    return `M${x},${base} V${top + r} Q${x},${top} ${x + r},${top} H${x + w - r} Q${x + w},${top} ${x + w},${top + r} V${base} Z`;
  }

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full" role="img" aria-label="Custo por dia nos últimos 30 dias">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} stroke={GRID} strokeWidth={1} />
            <text x={pad.l - 8} y={y(t) + 4} textAnchor="end" className="fill-dim font-mono" fontSize={11}>
              {t === 0 ? "$0" : usd(t, tickDigits)}
            </text>
          </g>
        ))}
        {series.map((d, i) => {
          const x = pad.l + i * slot + (slot - barW) / 2;
          const top = y(d.cost);
          return (
            <g key={d.day}>
              <path d={barPath(x, top, barW)} fill={hover === i ? SERIES_HOVER : SERIES} />
              <rect
                x={pad.l + i * slot}
                y={pad.t}
                width={slot}
                height={innerH}
                fill="transparent"
                tabIndex={0}
                aria-label={`${shortDay(d.day)}: ${usd(d.cost)}`}
                onPointerEnter={() => setHover(i)}
                onPointerLeave={() => setHover(null)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
                style={{ outline: "none", cursor: "default" }}
              />
              {(i % 5 === 4 || i === series.length - 1) && (
                <text x={pad.l + i * slot + slot / 2} y={H - 8} textAnchor="middle" className="fill-dim font-mono" fontSize={10.5}>
                  {shortDay(d.day)}
                </text>
              )}
            </g>
          );
        })}
        {series[peak].cost > 0 && (
          <text x={pad.l + peak * slot + slot / 2} y={y(series[peak].cost) - 6} textAnchor="middle" className="fill-muted font-mono" fontSize={11}>
            {usd(series[peak].cost)}
          </text>
        )}
      </svg>
      {hover !== null && (
        <div
          className="pointer-events-none absolute top-0 z-10 -translate-x-1/2 border border-edge bg-ink px-2.5 py-1.5 shadow-lg"
          style={{ left: `${((pad.l + hover * slot + slot / 2) / W) * 100}%` }}
        >
          <div className="tnum font-mono text-[14px] text-paper">{usd(series[hover].cost)}</div>
          <div className="flex items-center gap-1.5 font-mono text-[10.5px] text-muted">
            <span className="inline-block h-[2px] w-3" style={{ background: SERIES }} /> {shortDay(series[hover].day)}
          </div>
        </div>
      )}
    </div>
  );
}
