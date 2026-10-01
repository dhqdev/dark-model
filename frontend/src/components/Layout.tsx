import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { LogOut, Menu, X } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { usd } from "../lib/format";
import type { Balance, SystemStatus } from "../lib/types";

const NAV = [
  { to: "/", label: "Console", n: "01", end: true },
  { to: "/canais", label: "Canais", n: "02" },
  { to: "/fila", label: "Fila de geração", n: "03" },
  { to: "/consumo", label: "Consumo e custos", n: "04" },
  { to: "/ajustes", label: "Configurações", n: "05" },
];

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <svg width="30" height="30" viewBox="0 0 64 64" aria-hidden>
        <rect x="10" y="24" width="44" height="30" fill="none" stroke="#f0a43a" strokeWidth="3" />
        <path d="M10 14 L54 10 L54 20 L10 24 Z" fill="none" stroke="#f0a43a" strokeWidth="3" />
        <path d="M20 13 L16 23 M32 12 L28 22 M44 11 L40 21" stroke="#f0a43a" strokeWidth="3" />
        <circle cx="32" cy="39" r="5" fill="#e45a3f" />
      </svg>
      <div className="leading-none">
        <div className="display text-[21px] font-normal tracking-tight">
          Dark<span className="text-amber">·</span>Model
        </div>
        {!compact && <div className="mt-1 font-mono text-[9px] tracking-[0.2em] whitespace-nowrap text-dim uppercase">Faceless production</div>}
      </div>
    </div>
  );
}

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(t);
  }, []);
  return <span className="tnum font-mono text-[11px] tracking-[0.14em] text-muted">{now.toLocaleTimeString("pt-BR")}</span>;
}

function useSystem() {
  const status = useQuery({
    queryKey: ["system"],
    queryFn: () => api.get<SystemStatus>("/system/status"),
    refetchInterval: 10_000,
  });
  const balance = useQuery({
    queryKey: ["balance"],
    queryFn: () => api.get<Balance>("/usage/balance"),
    refetchInterval: 120_000,
    enabled: !!status.data?.openrouter_configured,
  });
  return { status: status.data, balance: balance.data };
}

function SystemBox() {
  const { status, balance } = useSystem();
  const { logout } = useAuth();
  const running = Object.entries(status?.queue ?? {}).filter(([k]) => k.endsWith(":running")).reduce((s, [, v]) => s + v, 0);
  const queued = Object.entries(status?.queue ?? {}).filter(([k]) => k.endsWith(":queued")).reduce((s, [, v]) => s + v, 0);
  const workers = status?.workers.length ?? 0;
  return (
    <div className="space-y-2.5 border-t border-line px-5 py-4 font-mono text-[10.5px] tracking-[0.12em] uppercase">
      <div className="flex items-center justify-between text-muted">
        <span>Worker</span>
        <span className="flex items-center gap-2 text-paper">
          <span className={clsx("led", workers ? "led-ok" : "led-err")} />
          {workers ? `${workers} online` : "offline"}
        </span>
      </div>
      <div className="flex items-center justify-between text-muted">
        <span>Fila</span>
        <span className="tnum text-paper">
          {running} rodando · {queued} fila
        </span>
      </div>
      <div className="flex items-center justify-between text-muted" title={balance?.reason ?? (balance?.source === "key_limit" ? "Limite restante da chave" : "Saldo da conta")}>
        <span>OpenRouter</span>
        <span className="tnum text-amber">{!status?.openrouter_configured ? "sem chave" : balance?.available ? usd(balance.balance, 2) : "—"}</span>
      </div>
      <div className="flex items-center justify-between pt-1 text-dim">
        <span>v{__APP_VERSION__}</span>
        <button className="flex items-center gap-1.5 text-muted hover:text-amber" onClick={() => void logout()}>
          <LogOut size={12} /> Sair
        </button>
      </div>
    </div>
  );
}

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex-1 space-y-0.5 px-3 py-4">
      {NAV.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          onClick={onNavigate}
          className={({ isActive }) =>
            clsx(
              "group flex items-center gap-3 border-l-2 px-3 py-2.5 transition-colors",
              isActive ? "border-amber bg-raised text-paper" : "border-transparent text-muted hover:bg-raised/60 hover:text-paper",
            )
          }
        >
          <span className="font-mono text-[10px] tracking-[0.14em] text-dim group-hover:text-amber">{item.n}</span>
          <span className="text-[13.5px]">{item.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}

export function Layout() {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const { status } = useSystem();
  const running = Object.entries(status?.queue ?? {}).filter(([k]) => k.endsWith(":running")).reduce((s, [, v]) => s + v, 0);
  useEffect(() => setOpen(false), [location.pathname]);

  return (
    <div className="min-h-screen md:grid md:grid-cols-[248px_1fr]">
      <aside className="sticky top-0 hidden h-screen flex-col border-r border-line bg-coal md:flex">
        <div className="border-b border-line px-5 py-5">
          <Logo />
        </div>
        <Nav />
        <SystemBox />
      </aside>

      {open && (
        <div className="fixed inset-0 z-40 flex md:hidden">
          <div className="flex w-72 flex-col border-r border-line bg-coal">
            <div className="flex items-center justify-between border-b border-line px-5 py-4">
              <Logo />
              <button className="btn btn-icon border-transparent" onClick={() => setOpen(false)} aria-label="Fechar menu">
                <X size={16} />
              </button>
            </div>
            <Nav onNavigate={() => setOpen(false)} />
            <SystemBox />
          </div>
          <div className="flex-1 bg-ink/70" onClick={() => setOpen(false)} />
        </div>
      )}

      <div className="min-w-0">
        <div className="sticky top-0 z-30 flex h-11 items-center justify-between border-b border-line bg-ink/90 px-4 backdrop-blur md:px-8">
          <div className="flex items-center gap-3">
            <button className="btn btn-icon border-transparent md:hidden" onClick={() => setOpen(true)} aria-label="Abrir menu">
              <Menu size={16} />
            </button>
            <div className="md:hidden">
              <Logo compact />
            </div>
            <span className="hidden font-mono text-[10.5px] tracking-[0.2em] text-dim uppercase md:inline">Studio · single user</span>
          </div>
          <div className="flex items-center gap-4">
            {running > 0 && (
              <span className="flex items-center gap-2 font-mono text-[10.5px] tracking-[0.2em] text-signal uppercase" title={`${running} tarefas rodando`}>
                <span className="led led-err animate-pulse" /> Rec · {running}
              </span>
            )}
            <Clock />
          </div>
        </div>
        <main className="mx-auto w-full max-w-[1400px] px-4 py-8 md:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
