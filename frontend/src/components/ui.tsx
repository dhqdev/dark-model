import clsx from "clsx";
import { X } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";
import { errorMessage } from "../lib/api";
import { SOURCE_LABEL, STATUS_LABEL } from "../lib/format";

export function PageHeader({
  kicker,
  title,
  subtitle,
  actions,
}: {
  kicker: string;
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-8 flex flex-col gap-4 border-b border-line pb-6 md:flex-row md:items-end md:justify-between">
      <div className="min-w-0">
        <div className="kicker mb-2">{kicker}</div>
        <h1 className="display text-[38px] leading-[1.02] font-light tracking-tight text-paper md:text-[48px]">{title}</h1>
        {subtitle && <div className="mt-2 max-w-3xl text-[13.5px] text-muted">{subtitle}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Panel({
  index,
  title,
  actions,
  children,
  className,
  bodyClass,
}: {
  index?: string;
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClass?: string;
}) {
  return (
    <section className={clsx("panel", className)}>
      {(title || actions) && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5">
          <div className="flex min-w-0 items-center gap-3">
            {index && <span className="font-mono text-[10.5px] tracking-[0.16em] text-amber">{index}</span>}
            {title && <h2 className="truncate font-mono text-[11px] tracking-[0.18em] text-paper uppercase">{title}</h2>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={clsx("p-4", bodyClass)}>{children}</div>
    </section>
  );
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "danger";
  size?: "sm" | "md";
  loading?: boolean;
  icon?: ReactNode;
};

export function Btn({ variant = "ghost", size = "md", loading, icon, children, className, disabled, ...rest }: BtnProps) {
  return (
    <button
      type="button"
      {...rest}
      disabled={disabled || loading}
      className={clsx(
        "btn",
        variant === "primary" && "btn-primary",
        variant === "danger" && "btn-danger",
        size === "sm" && "btn-sm",
        className,
      )}
    >
      {loading ? <span className="led led-run" /> : icon}
      {children}
    </button>
  );
}

export function Field({ label, hint, children, className }: { label: string; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={clsx("block", className)}>
      <span className="label">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[12px] text-dim">{hint}</span>}
    </label>
  );
}

export function Badge({
  tone = "default",
  children,
  className,
  title,
}: {
  tone?: "default" | "amber" | "ok" | "err" | "info" | "dim";
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={clsx(
        "inline-flex items-center gap-1 border px-1.5 py-[1px] font-mono text-[10px] tracking-[0.12em] uppercase whitespace-nowrap",
        tone === "default" && "border-edge text-muted",
        tone === "amber" && "border-amber/60 text-amber",
        tone === "ok" && "border-ok/50 text-ok",
        tone === "err" && "border-signal/60 text-signal",
        tone === "info" && "border-info/50 text-info",
        tone === "dim" && "border-line text-dim",
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Led({ status, title }: { status: string; title?: string }) {
  const cls =
    status === "running" ? "led-run" : status === "queued" ? "led-wait" : status === "failed" ? "led-err" : status === "succeeded" || status === "ok" ? "led-ok" : "led-off";
  return <span className={clsx("led", cls)} title={title ?? STATUS_LABEL[status] ?? status} />;
}

export function Meter({ value, segments = 24, tone, className }: { value: number; segments?: number; tone?: "ok" | "err"; className?: string }) {
  const filled = Math.round(Math.max(0, Math.min(1, value)) * segments);
  return (
    <div className={clsx("meter", tone, className)} role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
      {Array.from({ length: segments }, (_, i) => (
        <span key={i} className={i < filled ? "on" : ""} />
      ))}
    </div>
  );
}

export function Stat({ label, value, sub, accent }: { label: string; value: ReactNode; sub?: ReactNode; accent?: boolean }) {
  return (
    <div className="min-w-0 px-4 py-3.5">
      <div className="kicker mb-1.5 truncate">{label}</div>
      <div className={clsx("tnum truncate font-mono text-[22px] leading-none", accent ? "text-amber" : "text-paper")}>{value}</div>
      {sub && <div className="mt-1.5 truncate text-[12px] text-dim">{sub}</div>}
    </div>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  disabled,
}: {
  options: { value: T; label: ReactNode; hint?: string }[];
  value: T;
  onChange: (v: T) => void;
  disabled?: boolean;
}) {
  return (
    <div className="inline-flex border border-edge">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          title={o.hint}
          disabled={disabled}
          onClick={() => onChange(o.value)}
          className={clsx(
            "border-r border-edge px-2.5 py-1.5 font-mono text-[10.5px] tracking-[0.1em] uppercase last:border-r-0 transition-colors",
            o.value === value ? "bg-amber text-ink" : "text-muted hover:text-paper",
            disabled && "cursor-not-allowed opacity-50",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/80 p-4 pt-[6vh] backdrop-blur-[2px]" onMouseDown={onClose}>
      <div className={clsx("panel w-full", wide ? "max-w-5xl" : "max-w-xl")} onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-modal>
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <h3 className="display text-[22px] font-light">{title}</h3>
          <button className="btn btn-icon border-transparent" onClick={onClose} aria-label="Fechar">
            <X size={16} />
          </button>
        </div>
        <div className="p-4">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-line px-4 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function Empty({ title, text, action }: { title: string; text?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 border border-dashed border-edge px-6 py-12 text-center">
      <div className="display text-[24px] font-light text-paper">{title}</div>
      {text && <div className="max-w-md text-[13px] text-muted">{text}</div>}
      {action}
    </div>
  );
}

export function Loading({ label = "Carregando" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-10 font-mono text-[11px] tracking-[0.18em] text-muted uppercase">
      <span className="led led-run" /> {label}…
    </div>
  );
}

export function ErrorBox({ error, title = "Algo deu errado" }: { error: unknown; title?: string }) {
  if (!error) return null;
  return (
    <div className="border border-signal/50 bg-signal/5 px-3 py-2.5 text-[13px] text-signal">
      <span className="font-mono text-[10.5px] tracking-[0.16em] uppercase">{title}: </span>
      {errorMessage(error)}
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "amber" | "err" | "ok"; children: ReactNode }) {
  return (
    <div
      className={clsx(
        "border-l-2 px-3 py-2 text-[13px]",
        tone === "info" && "border-info bg-info/5 text-paper",
        tone === "amber" && "border-amber bg-amber/5 text-paper",
        tone === "err" && "border-signal bg-signal/5 text-paper",
        tone === "ok" && "border-ok bg-ok/5 text-paper",
      )}
    >
      {children}
    </div>
  );
}

export function SourceMark({ source, note }: { source: string; note?: string }) {
  const glyph = { live: "●", history: "◆", heuristic: "≈", free: "○", unavailable: "—" }[source] ?? "?";
  const color = { live: "text-ok", history: "text-amber", heuristic: "text-info", free: "text-dim", unavailable: "text-signal" }[source] ?? "";
  return (
    <span className={clsx("cursor-help font-mono", color)} title={`${SOURCE_LABEL[source] ?? source}${note ? ` — ${note}` : ""}`}>
      {glyph}
    </span>
  );
}

// ---------------------------------------------------------------- avisos rápidos

interface Toast {
  id: number;
  text: string;
  tone: "ok" | "err" | "info";
}
const ToastCtx = createContext<(text: string, tone?: Toast["tone"]) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: Toast["tone"] = "ok") => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs, { id, text, tone }]);
    window.setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), tone === "err" ? 8000 : 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed right-4 bottom-4 z-[90] flex w-[min(420px,calc(100vw-2rem))] flex-col gap-2">
        {items.map((t) => (
          <div
            key={t.id}
            className={clsx(
              "panel pointer-events-auto px-3 py-2.5 text-[13px]",
              t.tone === "err" && "border-signal/60 text-signal",
              t.tone === "ok" && "text-paper",
              t.tone === "info" && "text-info",
            )}
          >
            <span className="mr-2 font-mono text-[10px] tracking-[0.16em] text-dim uppercase">
              {t.tone === "err" ? "erro" : t.tone === "ok" ? "ok" : "info"}
            </span>
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  return useContext(ToastCtx);
}

// ---------------------------------------------------------------- markdown mínimo (sem HTML bruto)

function inline(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**")) return <strong key={i}>{p.slice(2, -2)}</strong>;
    if (p.startsWith("`") && p.endsWith("`")) return <code key={i}>{p.slice(1, -1)}</code>;
    return p;
  });
}

export function MarkdownView({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) {
      blocks.push(
        <ul key={`ul${blocks.length}`}>
          {list.map((li, i) => (
            <li key={i}>{inline(li)}</li>
          ))}
        </ul>,
      );
      list = [];
    }
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*(?:[-*]|\d+\.)\s+(.*)$/);
    if (bullet) {
      list.push(bullet[1]);
      continue;
    }
    flush();
    if (!line.trim()) continue;
    const h = line.match(/^(#{1,3})\s+(.*)$/);
    if (h) {
      const level = h[1].length;
      const content = inline(h[2]);
      blocks.push(level === 1 ? <h1 key={blocks.length}>{content}</h1> : level === 2 ? <h2 key={blocks.length}>{content}</h2> : <h3 key={blocks.length}>{content}</h3>);
    } else {
      blocks.push(<p key={blocks.length}>{inline(line)}</p>);
    }
  }
  flush();
  return <div className="prose-dm text-[14px] leading-relaxed">{blocks}</div>;
}

// ---------------------------------------------------------------- diff de linhas (Skill)

export function LineDiff({ before, after }: { before: string; after: string }) {
  const a = before.split("\n");
  const b = after.split("\n");
  const n = a.length;
  const m = b.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const rows: { kind: " " | "+" | "-"; text: string }[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      rows.push({ kind: " ", text: a[i] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) rows.push({ kind: "-", text: a[i++] });
    else rows.push({ kind: "+", text: b[j++] });
  }
  while (i < n) rows.push({ kind: "-", text: a[i++] });
  while (j < m) rows.push({ kind: "+", text: b[j++] });
  return (
    <pre className="max-h-[60vh] overflow-auto border border-line bg-coal p-3 font-mono text-[12px] leading-relaxed whitespace-pre-wrap">
      {rows.map((r, k) => (
        <div key={k} className={clsx(r.kind === "+" && "bg-ok/10 text-ok", r.kind === "-" && "bg-signal/10 text-signal line-through decoration-signal/40", r.kind === " " && "text-muted")}>
          <span className="mr-2 select-none text-dim">{r.kind}</span>
          {r.text || " "}
        </div>
      ))}
    </pre>
  );
}
