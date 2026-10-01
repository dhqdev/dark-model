import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { ChannelForm, EMPTY_CHANNEL, type ChannelDraft } from "../components/ChannelForm";
import { Badge, Btn, Empty, ErrorBox, Loading, Modal, PageHeader } from "../components/ui";
import { api } from "../lib/api";
import { LANGUAGES, QUALITY_LABEL, usd } from "../lib/format";
import type { Channel } from "../lib/types";

export function Channels() {
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data, isLoading, error } = useQuery({ queryKey: ["channels"], queryFn: () => api.get<Channel[]>("/channels") });
  const create = useMutation({
    mutationFn: (d: ChannelDraft) => api.post<Channel>("/channels", { ...d, skill: d.skill?.trim() ? d.skill : null }),
    onSuccess: (c) => {
      void qc.invalidateQueries({ queryKey: ["channels"] });
      setOpen(false);
      navigate(`/canais/${c.id}`);
    },
  });

  return (
    <div>
      <PageHeader
        kicker="02 / Canais"
        title="Canais"
        subtitle="Cada canal tem idioma, público, estilo, voz e uma Skill própria que evolui a cada projeto aprovado."
        actions={
          <Btn variant="primary" icon={<Plus size={13} />} onClick={() => setOpen(true)}>
            Novo canal
          </Btn>
        }
      />
      {isLoading && <Loading />}
      <ErrorBox error={error} />
      {data && data.length === 0 && (
        <Empty
          title="Nenhum canal cadastrado"
          text="Comece criando um canal: idioma, nicho, tom e estilo visual. A Skill inicial é criada automaticamente."
          action={
            <Btn variant="primary" onClick={() => setOpen(true)}>
              Criar primeiro canal
            </Btn>
          }
        />
      )}
      <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        {data?.map((c) => (
          <Link key={c.id} to={`/canais/${c.id}`} className="panel group block p-5 transition-colors hover:border-edge hover:bg-raised">
            <div className="mb-4 flex items-start justify-between gap-3">
              <Badge tone="amber">{c.language}</Badge>
              <span className="font-mono text-[10px] tracking-[0.16em] text-dim uppercase">Skill v{c.stats.skill_version ?? 1}</span>
            </div>
            <h3 className="display mb-1 text-[26px] leading-tight font-light group-hover:text-amber">{c.name}</h3>
            <div className="mb-4 line-clamp-2 min-h-[2.6em] text-[13px] text-muted">
              {c.niche || "Nicho não definido"} · {LANGUAGES.find((l) => l.code === c.language)?.label ?? c.language}
            </div>
            <div className="grid grid-cols-3 border-t border-line pt-3 font-mono text-[11px]">
              <div>
                <div className="kicker">Projetos</div>
                <div className="tnum mt-1 text-paper">{c.stats.projects ?? 0}</div>
              </div>
              <div>
                <div className="kicker">Custo</div>
                <div className="tnum mt-1 text-paper">{usd(c.stats.cost ?? 0, 2)}</div>
              </div>
              <div>
                <div className="kicker">Padrão</div>
                <div className="mt-1 text-paper">{QUALITY_LABEL[c.default_quality]}</div>
              </div>
            </div>
            {(c.stats.pending_learnings ?? 0) > 0 && (
              <div className="mt-3 font-mono text-[10.5px] tracking-[0.12em] text-amber uppercase">● {c.stats.pending_learnings} aprendizados para revisar</div>
            )}
          </Link>
        ))}
      </div>
      <Modal open={open} onClose={() => setOpen(false)} title="Novo canal" wide>
        <ChannelForm initial={EMPTY_CHANNEL} onSubmit={(d) => create.mutate(d)} submitLabel="Criar canal" busy={create.isPending} error={create.error} />
      </Modal>
    </div>
  );
}
