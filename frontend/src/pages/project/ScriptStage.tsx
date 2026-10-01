import clsx from "clsx";
import { Save, ScanSearch } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Btn, Meter, Notice, Panel, useToast } from "../../components/ui";
import { api, errorMessage } from "../../lib/api";
import { dateTime, minutes } from "../../lib/format";
import type { ProjectDetail } from "../../lib/types";
import { countWords, ISSUE_LABEL, RISK_LABEL, SCORE_LABEL, useInvalidateProject, useProjectAction } from "./shared";

const VERDICT: Record<string, { label: string; tone: "ok" | "amber" | "err" }> = {
  approved: { label: "Aprovado", tone: "ok" },
  needs_revision: { label: "Precisa de revisão", tone: "amber" },
  high_risk: { label: "Alto risco", tone: "err" },
};

const SEV_TONE = { low: "dim", medium: "amber", high: "err" } as const;
const SEV_LABEL = { low: "baixa", medium: "média", high: "alta" };

export function ScriptStage({ project }: { project: ProjectDetail }) {
  const [text, setText] = useState(project.script);
  const [saving, setSaving] = useState(false);
  const toast = useToast();
  const invalidate = useInvalidateProject(project.id);
  const analyze = useProjectAction(project.id, "analyze", "Análise do roteiro na fila");
  useEffect(() => setText(project.script), [project.script]);
  const dirty = text !== project.script;
  const wpm = project.channel.words_per_minute ?? project.channel.default_wpm;
  const words = countWords(text);
  const estMin = words / wpm;
  const { duration_min: min, duration_max: max } = project.channel;
  const within = estMin >= min && estMin <= max;

  async function save() {
    setSaving(true);
    try {
      await api.patch(`/projects/${project.id}`, { script: text });
      invalidate();
      toast("Roteiro salvo");
    } catch (e) {
      toast(errorMessage(e), "err");
    } finally {
      setSaving(false);
    }
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        if (dirty) void save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const a = project.analysis;
  const ai = a?.ai;
  const verdict = ai ? VERDICT[ai.verdict] : null;

  return (
    <div className="grid gap-6 2xl:grid-cols-[1.05fr_1fr]">
      <Panel
        index="01"
        title="Roteiro"
        actions={
          <>
            <Btn size="sm" icon={<Save size={11} />} disabled={!dirty} loading={saving} onClick={() => void save()}>
              Salvar
            </Btn>
            <Btn
              size="sm"
              variant="primary"
              icon={<ScanSearch size={11} />}
              loading={analyze.isPending}
              disabled={words < 30}
              onClick={async () => {
                if (dirty) await save();
                analyze.mutate(undefined);
              }}
            >
              Analisar com IA
            </Btn>
          </>
        }
      >
        <div className="mb-3 grid grid-cols-3 gap-px border border-line bg-line font-mono text-[11px]">
          <div className="bg-panel px-3 py-2">
            <div className="kicker">Palavras</div>
            <div className="tnum mt-1 text-[15px] text-paper">{words.toLocaleString("pt-BR")}</div>
          </div>
          <div className="bg-panel px-3 py-2">
            <div className="kicker">Duração estimada</div>
            <div className={clsx("tnum mt-1 text-[15px]", words ? (within ? "text-ok" : "text-amber") : "text-dim")}>{minutes(estMin * 60)}</div>
          </div>
          <div className="bg-panel px-3 py-2">
            <div className="kicker">Alvo do canal</div>
            <div className="tnum mt-1 text-[15px] text-paper">
              {min}–{max} min
            </div>
          </div>
        </div>
        <Meter value={Math.min(1, estMin / max)} tone={within ? "ok" : undefined} segments={40} className="mb-3" />
        <textarea
          className="input min-h-[62vh] text-[15px] leading-[1.75]"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={`Cole ou escreva o roteiro em ${project.channel.language}. Parágrafos separados por linha em branco ajudam a divisão em cenas.`}
          spellCheck={false}
        />
        <div className="mt-2 text-[11.5px] text-dim">
          {wpm} palavras/min ({project.channel.language}) · Ctrl+S salva · {dirty ? <span className="text-amber">alterações não salvas</span> : "salvo"}
        </div>
      </Panel>

      <Panel index="A" title="Análise da IA" actions={a ? <span className="font-mono text-[10.5px] text-dim">{a.model} · {dateTime(a.created_at)}</span> : undefined}>
        {!ai && <div className="py-10 text-center text-[13px] text-dim">Salve o roteiro e clique em “Analisar com IA”: estrutura, coerência, repetição, duração, adequação ao canal e riscos de política do YouTube.</div>}
        {ai && (
          <div className="space-y-6">
            {!project.stages.script.analysis_fresh && <Notice tone="amber">O roteiro mudou depois desta análise. Analise novamente para atualizar.</Notice>}
            <div className="flex flex-wrap items-center gap-3">
              {verdict && <Badge tone={verdict.tone}>{verdict.label}</Badge>}
              <span className="text-[13px] text-muted">{ai.summary}</span>
            </div>
            <div className="grid grid-cols-2 gap-x-6 gap-y-3 md:grid-cols-3">
              {Object.entries(ai.scores)
                .filter((e): e is [string, number] => typeof e[1] === "number")
                .map(([k, v]) => (
                <div key={k}>
                  <div className="mb-1 flex justify-between font-mono text-[10.5px] tracking-[0.12em] uppercase">
                    <span className="text-muted">{SCORE_LABEL[k] ?? k}</span>
                    <span className="tnum text-paper">{v}/10</span>
                  </div>
                  <Meter value={v / 10} segments={10} tone={v >= 7 ? "ok" : v < 5 ? "err" : undefined} />
                </div>
              ))}
            </div>

            {ai.policy_risks.length > 0 ? (
              <section>
                <h4 className="kicker mb-2 text-signal">Riscos de política · {ai.policy_risks.length}</h4>
                <div className="space-y-2">
                  {ai.policy_risks.map((r, i) => (
                    <div key={i} className={clsx("border-l-2 px-3 py-2", r.severity === "high" ? "border-signal bg-signal/5" : "border-amber bg-amber/5")}>
                      <div className="mb-1 flex flex-wrap items-center gap-2">
                        <Badge tone={SEV_TONE[r.severity]}>{SEV_LABEL[r.severity]}</Badge>
                        <span className="font-mono text-[11px] tracking-[0.12em] text-paper uppercase">{RISK_LABEL[r.category] ?? r.category}</span>
                      </div>
                      <div className="text-[13px] text-paper">{r.explanation}</div>
                      {r.excerpt && <div className="mt-1 text-[12.5px] text-muted italic">“{r.excerpt}”</div>}
                      <div className="mt-1 text-[12.5px] text-ok">→ {r.recommendation}</div>
                    </div>
                  ))}
                </div>
              </section>
            ) : (
              <Notice tone="ok">Nenhum risco de política identificado (copyright, spam, conteúdo reutilizado, desinformação…).</Notice>
            )}

            <section className="grid gap-4 md:grid-cols-2">
              {[
                ["Gancho", ai.hook_assessment],
                ["Ritmo e duração", ai.pacing_assessment],
                ["Final", ai.ending_assessment],
                ["Adequação ao canal", ai.channel_fit_assessment],
                ["Originalidade", ai.originality_assessment],
              ].map(([k, v]) => (
                <div key={k}>
                  <div className="kicker mb-1">{k}</div>
                  <div className="text-[13px] leading-relaxed text-paper">{v}</div>
                </div>
              ))}
            </section>

            {ai.structure.length > 0 && (
              <section>
                <h4 className="kicker mb-2">Estrutura</h4>
                <ol className="space-y-1.5">
                  {ai.structure.map((s, i) => (
                    <li key={i} className="grid grid-cols-[28px_1fr] text-[13px]">
                      <span className="font-mono text-amber">{String(i + 1).padStart(2, "0")}</span>
                      <span>
                        <span className="text-paper">{s.title}</span> <span className="text-dim italic">“{s.starts_with}…”</span>
                        <span className="block text-muted">{s.assessment}</span>
                      </span>
                    </li>
                  ))}
                </ol>
              </section>
            )}

            {ai.issues.length > 0 && (
              <section>
                <h4 className="kicker mb-2">Problemas · {ai.issues.length}</h4>
                <div className="space-y-2">
                  {[...ai.issues]
                    .sort((x, y) => ["high", "medium", "low"].indexOf(x.severity) - ["high", "medium", "low"].indexOf(y.severity))
                    .map((it, i) => (
                      <div key={i} className="border border-line px-3 py-2">
                        <div className="mb-1 flex items-center gap-2">
                          <Badge tone={SEV_TONE[it.severity]}>{SEV_LABEL[it.severity]}</Badge>
                          <span className="font-mono text-[10.5px] tracking-[0.12em] text-muted uppercase">{ISSUE_LABEL[it.type] ?? it.type}</span>
                        </div>
                        <div className="text-[13px]">{it.explanation}</div>
                        {it.excerpt && <div className="mt-1 text-[12.5px] text-dim italic">“{it.excerpt}”</div>}
                        <div className="mt-1 text-[12.5px] text-ok">→ {it.suggestion}</div>
                      </div>
                    ))}
                </div>
              </section>
            )}

            {(a!.metrics.repeated_sentences.length > 0 || a!.metrics.repeated_phrases.length > 0 || ai.repetition_notes.length > 0) && (
              <section>
                <h4 className="kicker mb-2">Repetições</h4>
                <ul className="space-y-1 text-[12.5px] text-muted">
                  {a!.metrics.repeated_sentences.map((r, i) => (
                    <li key={`s${i}`}>
                      <span className="font-mono text-amber">×{r.count}</span> {r.text}
                    </li>
                  ))}
                  {a!.metrics.repeated_phrases.map((r, i) => (
                    <li key={`p${i}`}>
                      <span className="font-mono text-amber">×{r.count}</span> “{r.text}”
                    </li>
                  ))}
                  {ai.repetition_notes.map((r, i) => (
                    <li key={`n${i}`}>• {r}</li>
                  ))}
                </ul>
              </section>
            )}

            {ai.improvements.length > 0 && (
              <section>
                <h4 className="kicker mb-2">Melhorias sugeridas</h4>
                <ol className="list-inside list-decimal space-y-1 text-[13px] text-paper marker:text-amber">
                  {ai.improvements.map((m, i) => (
                    <li key={i}>{m}</li>
                  ))}
                </ol>
              </section>
            )}
            <div className="text-[11.5px] text-dim">As sinalizações são preventivas e não substituem revisão humana/jurídica. Conteúdo original sempre tem prioridade.</div>
          </div>
        )}
      </Panel>
    </div>
  );
}
