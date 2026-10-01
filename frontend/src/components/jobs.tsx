import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { RotateCcw, Square } from "lucide-react";
import { Link } from "react-router";
import { api, errorMessage } from "../lib/api";
import { relative, STATUS_LABEL, usd } from "../lib/format";
import type { Job } from "../lib/types";
import { Led, Meter, useToast } from "./ui";

export function useJobActions() {
  const qc = useQueryClient();
  const toast = useToast();
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["jobs"] });
    void qc.invalidateQueries({ queryKey: ["project"] });
    void qc.invalidateQueries({ queryKey: ["dashboard"] });
  };
  const retry = useMutation({
    mutationFn: (id: number) => api.post<{ requeued: number }>(`/jobs/${id}/retry`),
    onSuccess: (r) => {
      toast(`${r.requeued} tarefa(s) de volta à fila`);
      refresh();
    },
    onError: (e) => toast(errorMessage(e), "err"),
  });
  const cancel = useMutation({
    mutationFn: (id: number) => api.post(`/jobs/${id}/cancel`),
    onSuccess: () => {
      toast("Cancelamento solicitado", "info");
      refresh();
    },
    onError: (e) => toast(errorMessage(e), "err"),
  });
  return { retry, cancel };
}

export function JobLine({ job, showProject = false, compact = false }: { job: Job; showProject?: boolean; compact?: boolean }) {
  const { retry, cancel } = useJobActions();
  const active = job.status === "queued" || job.status === "running";
  const failed = job.status === "failed" || job.status === "canceled";
  const counts = job.is_group && job.result ? (job.result as Record<string, number>) : null;
  return (
    <div className={clsx("grid items-center gap-x-4 gap-y-1.5 border-b border-line py-2.5 last:border-b-0", compact ? "grid-cols-[auto_1fr_auto]" : "grid-cols-[auto_1fr_auto] md:grid-cols-[auto_minmax(0,1.6fr)_minmax(140px,1fr)_auto]")}>
      <Led status={job.status} />
      <div className="min-w-0">
        <div className="truncate text-[13.5px] text-paper">{job.label}</div>
        <div className="truncate text-[12px] text-dim">
          {showProject && (job.project_title || job.channel_name) && (
            <>
              {job.project_id ? (
                <Link className="text-muted hover:text-amber" to={`/projetos/${job.project_id}`}>
                  {job.project_title}
                </Link>
              ) : (
                <span className="text-muted">{job.channel_name}</span>
              )}
              {" · "}
            </>
          )}
          <span className={clsx(job.status === "failed" && "text-signal")}>{job.status === "failed" && job.error ? job.error : job.message || STATUS_LABEL[job.status]}</span>
        </div>
      </div>
      {!compact && (
        <div className="col-span-3 flex items-center gap-3 md:col-span-1">
          <Meter value={job.progress} tone={job.status === "failed" ? "err" : job.status === "succeeded" ? "ok" : undefined} className="flex-1" />
          <span className="tnum w-24 text-right font-mono text-[11px] text-muted">
            {counts ? `${counts.succeeded ?? 0}/${counts.total ?? 0}` : `${Math.round(job.progress * 100)}%`}
          </span>
        </div>
      )}
      <div className="flex items-center gap-2 justify-self-end">
        <span className="tnum hidden font-mono text-[11px] text-muted sm:inline" title="Custo real desta tarefa">
          {job.cost ? usd(job.cost) : ""}
        </span>
        <span className="hidden font-mono text-[10.5px] text-dim lg:inline">{relative(job.finished_at ?? job.started_at ?? job.created_at)}</span>
        {active && (
          <button className="btn btn-sm btn-icon" title="Cancelar" onClick={() => cancel.mutate(job.id)} disabled={job.cancel_requested}>
            <Square size={11} />
          </button>
        )}
        {failed && (
          <button className="btn btn-sm" title="Repetir apenas o que falhou" onClick={() => retry.mutate(job.id)} disabled={retry.isPending}>
            <RotateCcw size={11} /> Repetir
          </button>
        )}
      </div>
    </div>
  );
}
