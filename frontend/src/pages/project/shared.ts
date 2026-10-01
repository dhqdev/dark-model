import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useToast } from "../../components/ui";
import { api, errorMessage } from "../../lib/api";
import type { Job } from "../../lib/types";

/** Dispara uma ação que cria job(s) e atualiza a tela do projeto. */
export function useProjectAction<TBody = unknown>(projectId: number, path: string, okText?: string) {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: (body?: TBody) => api.post<{ job?: Job | null; jobs?: Job[]; message?: string }>(path.startsWith("/") ? path : `/projects/${projectId}/${path}`, body ?? {}),
    onSuccess: (r) => {
      if (r && "job" in r && r.job === null && r.message) toast(r.message, "info");
      else if (okText) toast(okText, "info");
      void qc.invalidateQueries({ queryKey: ["project", projectId] });
      void qc.invalidateQueries({ queryKey: ["system"] });
    },
    onError: (e) => toast(errorMessage(e), "err"),
  });
}

export function useInvalidateProject(projectId: number) {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ["project", projectId] });
    void qc.invalidateQueries({ queryKey: ["estimate", projectId] });
  };
}

export const RISK_LABEL: Record<string, string> = {
  copyright: "Direitos autorais",
  reused_content: "Conteúdo reutilizado",
  inauthentic_content: "Conteúdo inautêntico / em massa",
  spam_deceptive: "Spam ou enganoso",
  misinformation: "Desinformação",
  violence_graphic: "Violência explícita",
  hate_harassment: "Ódio ou assédio",
  sexual_content: "Conteúdo sexual",
  dangerous_activities: "Atividades perigosas",
  medical_financial_claims: "Alegações médicas/financeiras",
  child_safety: "Segurança infantil",
  privacy: "Privacidade",
  synthetic_disclosure: "Divulgar conteúdo sintético",
  advertiser_unfriendly: "Pouco amigável a anunciantes",
  other: "Outro",
};

export const ISSUE_LABEL: Record<string, string> = {
  structure: "Estrutura",
  coherence: "Coerência",
  repetition: "Repetição",
  pacing: "Ritmo",
  clarity: "Clareza",
  factual: "Fato a verificar",
  length: "Duração",
  style: "Estilo",
  hook: "Gancho",
  ending: "Final",
  other: "Outro",
};

export const SCORE_LABEL: Record<string, string> = {
  hook: "Gancho",
  structure: "Estrutura",
  coherence: "Coerência",
  retention: "Retenção",
  originality: "Originalidade",
  channel_fit: "Adequação ao canal",
};

export function countWords(text: string): number {
  return (text.match(/[\p{L}\p{N}'’-]+/gu) ?? []).length;
}
