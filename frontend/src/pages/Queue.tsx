import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { JobLine } from "../components/jobs";
import { Empty, ErrorBox, Loading, PageHeader, Panel, Segmented } from "../components/ui";
import { api } from "../lib/api";
import type { Job } from "../lib/types";

type Filter = "active" | "failed" | "succeeded" | "all";

function GroupChildren({ id }: { id: number }) {
  const { data } = useQuery({ queryKey: ["jobs", "detail", id], queryFn: () => api.get<Job>(`/jobs/${id}`), refetchInterval: 3000 });
  if (!data?.children) return <div className="py-2 pl-10 text-[12px] text-dim">carregando…</div>;
  return (
    <div className="border-l border-edge pl-6 ml-2">
      {data.children.map((c) => (
        <JobLine key={c.id} job={c} />
      ))}
    </div>
  );
}

export function Queue() {
  const [filter, setFilter] = useState<Filter>("active");
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const { data, isLoading, error } = useQuery({
    queryKey: ["jobs", filter],
    queryFn: () => api.get<{ jobs: Job[]; counts: Record<string, number> }>(`/jobs?limit=150${filter === "all" ? "" : `&status=${filter}`}`),
    refetchInterval: (q) => (q.state.data?.jobs.some((j) => j.status === "running" || j.status === "queued") ? 2500 : 10000),
  });
  const c = data?.counts ?? {};
  return (
    <div>
      <PageHeader
        kicker="03 / Fila"
        title={
          <>
            Fila de <em className="text-amber">geração</em>
          </>
        }
        subtitle="Todas as tarefas pesadas rodam em segundo plano no worker. Se uma etapa falhar, “Repetir” refaz só o que falhou — nada é cobrado duas vezes por engano."
        actions={
          <Segmented
            value={filter}
            onChange={setFilter}
            options={[
              { value: "active", label: `Ativas ${(c.running ?? 0) + (c.queued ?? 0)}` },
              { value: "failed", label: `Falhas ${c.failed ?? 0}` },
              { value: "succeeded", label: `Concluídas ${c.succeeded ?? 0}` },
              { value: "all", label: "Todas" },
            ]}
          />
        }
      />
      {isLoading && <Loading />}
      <ErrorBox error={error} />
      {data && data.jobs.length === 0 && <Empty title="Fila vazia" text={filter === "active" ? "Nenhuma tarefa rodando ou aguardando." : "Nada por aqui."} />}
      {data && data.jobs.length > 0 && (
        <Panel bodyClass="py-1">
          {data.jobs.map((j) => (
            <div key={j.id}>
              <div className="flex items-start gap-2">
                {j.is_group ? (
                  <button className="mt-3 text-dim hover:text-amber" onClick={() => setOpen((o) => ({ ...o, [j.id]: !o[j.id] }))} aria-label="Detalhes do lote">
                    {open[j.id] ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  </button>
                ) : (
                  <span className="w-[14px]" />
                )}
                <div className="min-w-0 flex-1">
                  <JobLine job={j} showProject />
                </div>
              </div>
              {j.is_group && open[j.id] && <GroupChildren id={j.id} />}
            </div>
          ))}
        </Panel>
      )}
    </div>
  );
}
