import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { Badge, Btn, Loading, Modal, Notice, Panel, useToast } from "../../components/ui";
import { api, errorMessage } from "../../lib/api";
import { bytes } from "../../lib/format";
import type { ProjectDetail, ProjectStorage, StoragePart } from "../../lib/types";

const REGEN: Record<StoragePart["regen"], { label: string; tone: "ok" | "amber" | "dim" }> = {
  free: { label: "refaz de graça", tone: "ok" },
  paid: { label: "refazer custa", tone: "amber" },
  manual: { label: "não precisa refazer", tone: "dim" },
};

export function FilesStage({ project }: { project: ProjectDetail }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [confirm, setConfirm] = useState<StoragePart | null>(null);
  const { data, isLoading } = useQuery({
    queryKey: ["project-storage", project.id, project.size_bytes, project.updated_at],
    queryFn: () => api.get<ProjectStorage>(`/projects/${project.id}/storage`),
  });
  const remove = useMutation({
    mutationFn: (key: string) => api.del<{ label: string; freed_bytes: number; storage: ProjectStorage }>(`/projects/${project.id}/storage/${key}`),
    onSuccess: (r) => {
      toast(r.freed_bytes ? `${r.label}: ${bytes(r.freed_bytes)} liberados` : `${r.label}: excluído`);
      qc.setQueryData(["project-storage", project.id, project.size_bytes, project.updated_at], r.storage);
      void qc.invalidateQueries({ queryKey: ["project", project.id] });
      void qc.invalidateQueries({ queryKey: ["project-storage", project.id] });
      void qc.invalidateQueries({ queryKey: ["estimate", project.id] });
      setConfirm(null);
    },
    onError: (e) => toast(errorMessage(e), "err"),
  });

  if (isLoading || !data) return <Loading label="Medindo arquivos" />;
  const max = Math.max(1, ...data.parts.map((p) => p.bytes));

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
      <Panel index="▤" title={`Arquivos do projeto · ${bytes(data.disk_bytes)}`} bodyClass="p-0">
        <div className="divide-y divide-line">
          {data.parts.map((p) => {
            const empty = p.count === 0 && p.bytes === 0;
            const regen = REGEN[p.regen];
            return (
              <div key={p.key} className={clsx("grid gap-3 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_110px_auto] sm:items-center", empty && "opacity-55")}>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[14px] text-paper">{p.label}</span>
                    {p.count > 0 && <span className="font-mono text-[11px] text-dim">{p.count} {p.count === 1 ? "item" : "itens"}</span>}
                    {!empty && <Badge tone={regen.tone}>{regen.label}</Badge>}
                    {p.busy && <Badge tone="amber">gerando…</Badge>}
                  </div>
                  <div className="mt-0.5 text-[12px] text-dim">{p.note}</div>
                  <div className="mt-2 h-1.5 w-full bg-coal">
                    <div className="h-1.5 bg-amber/70" style={{ width: `${(p.bytes / max) * 100}%` }} />
                  </div>
                </div>
                <div className="tnum text-left font-mono text-[13px] text-paper sm:text-right">{p.bytes ? bytes(p.bytes) : "—"}</div>
                <div className="flex justify-start sm:justify-end">
                  <Btn size="sm" variant="danger" icon={<Trash2 size={11} />} disabled={empty || p.busy} onClick={() => setConfirm(p)}>
                    Excluir
                  </Btn>
                </div>
              </div>
            );
          })}
        </div>
      </Panel>

      <div className="space-y-6">
        <Panel title="Resumo">
          <div className="space-y-2 font-mono text-[12px]">
            <div className="flex justify-between">
              <span className="text-muted">No disco</span>
              <span className="tnum text-paper">{bytes(data.disk_bytes)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted">Arquivos registrados</span>
              <span className="tnum text-paper">{bytes(data.total_bytes)}</span>
            </div>
          </div>
          <p className="mt-4 text-[12.5px] text-muted">
            Para liberar espaço sem perder nada que está em uso, exclua <span className="text-paper">Versões antigas</span>, os{" "}
            <span className="text-paper">Pacotes ZIP</span> e os <span className="text-paper">Clipes de movimento</span> (refeitos de graça). O roteiro nunca é apagado
            aqui — para apagar o projeto inteiro, use o canal.
          </p>
        </Panel>
        <Notice tone="info">
          O vídeo final é o arquivo maior. Depois de baixar e publicar, você pode excluí-lo e montar de novo quando quiser em{" "}
          <Link to={`/projetos/${project.id}?etapa=video`} className="text-amber underline-offset-2 hover:underline">
            Vídeo final
          </Link>
          .
        </Notice>
      </div>

      <Modal
        open={confirm !== null}
        onClose={() => setConfirm(null)}
        title={confirm ? `Excluir ${confirm.label.toLowerCase()}?` : ""}
        footer={
          <Btn variant="danger" icon={<Trash2 size={12} />} loading={remove.isPending} onClick={() => confirm && remove.mutate(confirm.key)}>
            Excluir{confirm?.bytes ? ` e liberar ${bytes(confirm.bytes)}` : ""}
          </Btn>
        }
      >
        {confirm && (
          <div className="space-y-3 text-[13px] text-muted">
            <p>{confirm.note}</p>
            {confirm.regen === "paid" && <Notice tone="amber">Gerar de novo usa a OpenRouter e tem custo.</Notice>}
            <p className="text-dim">Não dá para desfazer.</p>
          </div>
        )}
      </Modal>
    </div>
  );
}
