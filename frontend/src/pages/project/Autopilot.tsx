import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Pause, Play, Rocket } from "lucide-react";
import { useState } from "react";
import { Btn, Modal, Notice, useToast } from "../../components/ui";
import { api, errorMessage } from "../../lib/api";
import { QUALITY_LABEL, brl, relative } from "../../lib/format";
import type { AutopilotStep, Estimate, ProjectDetail } from "../../lib/types";

const STEPS: { key: AutopilotStep; label: string }[] = [
  { key: "analysis", label: "Análise" },
  { key: "scenes", label: "Cenas" },
  { key: "narration", label: "Narração" },
  { key: "visuals", label: "Visuais" },
  { key: "render", label: "Vídeo final" },
  { key: "metadata", label: "Título/Desc." },
  { key: "thumbnail", label: "Thumbnail" },
  { key: "export", label: "ZIP" },
];

/** A etapa já está completa? (mesma regra do servidor em pipeline/autopilot.py) */
function stepDone(p: ProjectDetail, key: AutopilotStep): boolean {
  const s = p.stages;
  switch (key) {
    case "analysis":
      return s.script.analysis_fresh;
    case "scenes":
      return s.scenes.count > 0;
    case "narration":
      return s.narration.total > 0 && s.narration.ready === s.narration.total;
    case "visuals":
      return s.visuals.total > 0 && s.visuals.ready === s.visuals.total;
    case "render":
      return !!s.render.last && !s.render.outdated;
    case "metadata":
      return s.metadata.ready;
    case "thumbnail":
      return s.thumbnail.concepts > 0;
    case "export":
      return s.export.count > 0 && !s.export.outdated;
  }
}

export function AutopilotPanel({ project, estimate }: { project: ProjectDetail; estimate?: Estimate }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [confirm, setConfirm] = useState(false);
  const ap = project.autopilot;
  const act = useMutation({
    mutationFn: (body: { action: "start" | "stop"; ignore_risk?: boolean }) =>
      api.post<ProjectDetail>(`/projects/${project.id}/autopilot`, body),
    onSuccess: (p, body) => {
      qc.setQueryData(["project", project.id], p);
      setConfirm(false);
      toast(body.action === "stop" ? "Piloto automático desligado" : "Piloto automático ligado", "info");
    },
    onError: (e) => toast(errorMessage(e), "err"),
  });

  const tier = estimate?.tiers[project.quality];
  const missing = STEPS.filter((s) => !stepDone(project, s.key));
  const running = !!ap?.active;
  const paused = ap?.status === "paused";

  return (
    <section className={clsx("panel mb-6", running && "border-amber/60")}>
      <div className="flex flex-col gap-3 px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <span className={clsx("led", running ? "led-run" : paused ? "led-err" : ap?.status === "done" ? "led-ok" : "led-off")} />
          <div className="min-w-0">
            <div className="font-mono text-[11px] tracking-[0.18em] text-paper uppercase">Piloto automático</div>
            <div className="truncate text-[12.5px] text-muted">
              {running
                ? ap?.message
                : paused
                  ? "Pausado"
                  : ap?.status === "done"
                    ? `Concluído ${relative(ap.finished_at)}`
                    : missing.length
                      ? `Faz sozinho as ${missing.length} etapas que faltam, uma depois da outra`
                      : "Todas as etapas estão prontas"}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ol className="flex flex-wrap gap-1">
            {STEPS.map((s) => {
              const done = stepDone(project, s.key);
              const current = running && ap?.step === s.key;
              return (
                <li
                  key={s.key}
                  className={clsx(
                    "border px-1.5 py-[1px] font-mono text-[10px] tracking-[0.1em] uppercase whitespace-nowrap",
                    current ? "border-amber text-amber" : done ? "border-ok/50 text-ok" : "border-line text-dim",
                  )}
                  title={current ? "em andamento" : done ? "pronta" : "a fazer"}
                >
                  {current ? "▸ " : done ? "✓ " : ""}
                  {s.label}
                </li>
              );
            })}
          </ol>
          {running ? (
            <Btn size="sm" icon={<Pause size={14} />} loading={act.isPending} onClick={() => act.mutate({ action: "stop" })}>
              Parar
            </Btn>
          ) : (
            <Btn
              size="sm"
              variant="primary"
              icon={paused ? <Play size={14} /> : <Rocket size={14} />}
              disabled={missing.length === 0 || project.stages.script.words < 30}
              title={project.stages.script.words < 30 ? "Escreva o roteiro primeiro (mínimo de 30 palavras)" : undefined}
              onClick={() => setConfirm(true)}
            >
              {paused ? "Retomar" : "Ligar piloto automático"}
            </Btn>
          )}
        </div>
      </div>
      {paused && ap?.error && (
        <div className="border-t border-line px-4 py-3">
          <Notice tone={ap.reason === "risk" ? "amber" : "err"}>
            <div>{ap.error}</div>
            {ap.reason === "risk" ? (
              <div className="mt-2">
                <Btn size="sm" loading={act.isPending} onClick={() => act.mutate({ action: "start", ignore_risk: true })}>
                  Continuar mesmo assim
                </Btn>
              </div>
            ) : (
              <div className="mt-1 text-[12px] text-muted">
                Corrija o problema (saldo, modelo, cena) e clique em Retomar: ele refaz só o que falta, sem pagar de novo o que já deu certo.
              </div>
            )}
          </Notice>
        </div>
      )}

      <Modal
        open={confirm}
        onClose={() => setConfirm(false)}
        title="Ligar piloto automático"
        footer={
          <>
            <Btn onClick={() => setConfirm(false)}>Cancelar</Btn>
            <Btn variant="primary" icon={<Rocket size={14} />} loading={act.isPending} onClick={() => act.mutate({ action: "start" })}>
              Ligar
            </Btn>
          </>
        }
      >
        <div className="space-y-3 text-[13.5px]">
          <p>
            O sistema passa sozinho por cada etapa que falta, na ordem, e só gera o que ainda não existe:
          </p>
          <ol className="list-decimal space-y-0.5 pl-5 text-muted">
            {missing.map((s) => (
              <li key={s.key}>{s.label}</li>
            ))}
          </ol>
          {tier && (
            <Notice tone="amber">
              Plano {QUALITY_LABEL[project.quality]}: estimativa do projeto inteiro <b>{brl(tier.total_brl)}</b>
              {tier.cap_brl ? <> · teto {brl(tier.cap_brl)} {tier.fits === false ? "(passa do teto)" : "✓"}</> : null}.
              {" "}O que já foi gerado não é pago de novo.
            </Notice>
          )}
          <p className="text-[12.5px] text-dim">
            Pausa sozinho se uma tarefa falhar (ex.: saldo insuficiente) ou se a análise apontar alto risco de política do YouTube.
            Cenas que já têm imagens ou narração nunca são refeitas. Você pode parar a qualquer momento.
          </p>
        </div>
      </Modal>
    </section>
  );
}
