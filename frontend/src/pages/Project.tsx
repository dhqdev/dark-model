import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Pencil } from "lucide-react";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { useEstimate } from "../components/estimate";
import { JobLine } from "../components/jobs";
import { Badge, ErrorBox, Loading, Modal, Btn, Panel, useToast } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { PROJECT_STATUS, QUALITY_LABEL, timecode, usd } from "../lib/format";
import type { ProjectDetail, Quality } from "../lib/types";
import { CostsStage } from "./project/CostsStage";
import { ExportStage } from "./project/ExportStage";
import { MetadataStage } from "./project/MetadataStage";
import { NarrationStage } from "./project/NarrationStage";
import { ScenesStage } from "./project/ScenesStage";
import { ScriptStage } from "./project/ScriptStage";
import { ThumbnailStage } from "./project/ThumbnailStage";
import { VisualsStage } from "./project/VisualsStage";

const STAGES = [
  { key: "roteiro", n: "01", label: "Roteiro" },
  { key: "cenas", n: "02", label: "Cenas" },
  { key: "visuais", n: "03", label: "Visuais" },
  { key: "narracao", n: "04", label: "Narração" },
  { key: "thumbnail", n: "05", label: "Thumbnail" },
  { key: "metadados", n: "06", label: "Título/Desc." },
  { key: "exportacao", n: "07", label: "Exportação" },
  { key: "custos", n: "$", label: "Custos" },
] as const;

type StageKey = (typeof STAGES)[number]["key"];

function stageInfo(p: ProjectDetail, key: StageKey): { detail: string; state: "ok" | "queued" | "off" } {
  const s = p.stages;
  switch (key) {
    case "roteiro":
      return { detail: `${s.script.words} pal.`, state: s.script.analysis_fresh ? "ok" : s.script.ready ? "queued" : "off" };
    case "cenas":
      return { detail: `${s.scenes.count} cenas`, state: s.scenes.count ? (s.scenes.fresh ? "ok" : "queued") : "off" };
    case "visuais":
      return { detail: `${s.visuals.ready}/${s.visuals.total}`, state: s.visuals.total && s.visuals.ready === s.visuals.total ? "ok" : s.visuals.ready ? "queued" : "off" };
    case "narracao":
      return { detail: `${s.narration.ready}/${s.narration.total}`, state: s.narration.total && s.narration.ready === s.narration.total ? "ok" : s.narration.ready ? "queued" : "off" };
    case "thumbnail":
      return { detail: `${s.thumbnail.images} imgs`, state: s.thumbnail.selected ? "ok" : s.thumbnail.concepts ? "queued" : "off" };
    case "metadados":
      return { detail: s.metadata.ready ? "sugerido" : "—", state: s.metadata.ready && s.metadata.title ? "ok" : "off" };
    case "exportacao":
      return { detail: `${s.export.count} zip`, state: s.export.count ? (s.export.outdated ? "queued" : "ok") : "off" };
    default:
      return { detail: usd(p.costs.cost), state: "off" };
  }
}

export function Project() {
  const { projectId } = useParams();
  const id = Number(projectId);
  const [params, setParams] = useSearchParams();
  const stage = (STAGES.find((s) => s.key === params.get("etapa"))?.key ?? "roteiro") as StageKey;
  const qc = useQueryClient();
  const toast = useToast();
  const [renaming, setRenaming] = useState<string | null>(null);

  const { data: project, isLoading, error } = useQuery({
    queryKey: ["project", id],
    queryFn: () => api.get<ProjectDetail>(`/projects/${id}`),
    refetchInterval: (q) => ((q.state.data?.active_jobs.length ?? 0) > 0 ? 2000 : false),
  });
  const estimate = useEstimate(id, !!project);
  const setQuality = useMutation({
    mutationFn: (quality: Quality) => api.patch<ProjectDetail>(`/projects/${id}`, { quality }),
    onSuccess: (p) => {
      qc.setQueryData(["project", id], p);
      void qc.invalidateQueries({ queryKey: ["estimate", id] });
    },
    onError: (e) => toast(errorMessage(e), "err"),
  });
  const rename = useMutation({
    mutationFn: (title: string) => api.patch<ProjectDetail>(`/projects/${id}`, { title }),
    onSuccess: (p) => {
      qc.setQueryData(["project", id], p);
      setRenaming(null);
    },
  });

  if (isLoading) return <Loading />;
  if (error || !project) return <ErrorBox error={error} />;
  const planned = project.stages.scenes.count > 0;
  const wpm = project.channel.words_per_minute ?? project.channel.default_wpm;
  const duration = planned ? project.stages.scenes.duration : (project.stages.script.words / wpm) * 60;

  return (
    <div>
      <header className="mb-6 border-b border-line pb-5">
        <div className="kicker mb-2 flex flex-wrap items-center gap-2">
          <Link className="hover:text-amber" to={`/canais/${project.channel_id}`}>
            {project.channel.name}
          </Link>
          <span>/</span>
          <span>Projeto #{project.id}</span>
          <span>/</span>
          <span className="text-amber">{project.channel.language}</span>
        </div>
        <div className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
          <div className="min-w-0">
            <h1 className="display flex items-start gap-3 text-[34px] leading-[1.05] font-light tracking-tight md:text-[44px]">
              <span className="min-w-0 break-words">{project.title}</span>
              <button className="mt-3 text-dim hover:text-amber" onClick={() => setRenaming(project.title)} aria-label="Renomear">
                <Pencil size={15} />
              </button>
            </h1>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Badge tone={project.status === "exported" ? "ok" : "default"}>{PROJECT_STATUS[project.status] ?? project.status}</Badge>
              {project.selected_title && project.selected_title !== project.title && <span className="truncate text-[13px] text-muted">“{project.selected_title}”</span>}
            </div>
          </div>
          <div className="flex flex-wrap items-stretch gap-3">
            <div className="panel px-4 py-2.5">
              <div className="kicker">{planned ? "Duração" : "Duração est."}</div>
              <div className="tnum mt-1 font-mono text-[20px] text-paper">{timecode(duration)}</div>
            </div>
            <div className="panel px-4 py-2.5">
              <div className="kicker">Custo real</div>
              <div className="tnum mt-1 font-mono text-[20px] text-amber">{usd(project.costs.cost)}</div>
            </div>
            <div className="panel flex">
              {(["ECONOMY", "BALANCED", "PREMIUM"] as Quality[]).map((q) => (
                <button
                  key={q}
                  onClick={() => q !== project.quality && setQuality.mutate(q)}
                  className={clsx("border-r border-line px-4 py-2.5 text-left last:border-r-0 transition-colors", q === project.quality ? "bg-amber text-ink" : "hover:bg-raised")}
                  title="Estimativa total do projeto neste nível (preços reais da OpenRouter)"
                >
                  <div className={clsx("font-mono text-[10px] tracking-[0.16em] uppercase", q === project.quality ? "text-ink" : "text-dim")}>{QUALITY_LABEL[q]}</div>
                  <div className={clsx("tnum mt-1 font-mono text-[15px]", q === project.quality ? "text-ink" : "text-paper")}>
                    {estimate.data ? usd(estimate.data.tiers[q].total, 2) : "…"}
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>
      </header>

      <nav className="mb-6 flex overflow-x-auto border border-line bg-panel" role="tablist">
        {STAGES.map((s) => {
          const info = stageInfo(project, s.key);
          return (
            <button key={s.key} role="tab" aria-selected={stage === s.key} className="slate-tab" onClick={() => setParams({ etapa: s.key }, { replace: true })}>
              <span className="flex items-center justify-between gap-3">
                <span className="font-mono text-[10px] tracking-[0.16em] text-amber">{s.n}</span>
                {s.key !== "custos" && <span className={clsx("led", info.state === "ok" ? "led-ok" : info.state === "queued" ? "led-wait" : "led-off")} />}
              </span>
              <span className="font-mono text-[11px] tracking-[0.12em] uppercase">{s.label}</span>
              <span className="tnum font-mono text-[10.5px] text-dim">{info.detail}</span>
            </button>
          );
        })}
      </nav>

      {project.active_jobs.length > 0 && (
        <Panel title={`Em produção · ${project.active_jobs.length}`} className="mb-6" bodyClass="py-1">
          {project.active_jobs.map((j) => (
            <JobLine key={j.id} job={j} />
          ))}
        </Panel>
      )}

      {stage === "roteiro" && <ScriptStage project={project} />}
      {stage === "cenas" && <ScenesStage project={project} />}
      {stage === "visuais" && <VisualsStage project={project} />}
      {stage === "narracao" && <NarrationStage project={project} />}
      {stage === "thumbnail" && <ThumbnailStage project={project} />}
      {stage === "metadados" && <MetadataStage project={project} />}
      {stage === "exportacao" && <ExportStage project={project} />}
      {stage === "custos" && <CostsStage project={project} />}

      <Modal
        open={renaming !== null}
        onClose={() => setRenaming(null)}
        title="Renomear projeto"
        footer={
          <Btn variant="primary" disabled={!renaming?.trim()} loading={rename.isPending} onClick={() => renaming && rename.mutate(renaming)}>
            Salvar
          </Btn>
        }
      >
        <input className="input" value={renaming ?? ""} onChange={(e) => setRenaming(e.target.value)} autoFocus />
      </Modal>
    </div>
  );
}
