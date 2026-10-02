# Dark Model — guia para o Claude

Estúdio web **single-user** para produzir vídeos dark/faceless de YouTube (15–25 min):
roteiro → cenas → imagens/vídeos → narração → **vídeo final montado no servidor** → thumbnail →
título/descrição → ZIP para CapCut. Toda a IA passa pela **OpenRouter** (texto, imagem, TTS, vídeo);
a montagem é **ffmpeg local, sem custo**. O README (em pt-BR) descreve o produto para o usuário;
este arquivo e `docs/` descrevem o **código**, para mudar rápido.

## Como trabalhar neste repositório

- **Dono:** david (GitHub `dhqdev`). Escreve em português e quer rapidez. Responda em pt-BR.
- **Branch padrão é `default`** (não `main`). Ele autorizou commits **direto na `default`**, sem PR.
- Push na `default` → GitHub Actions (`.github/workflows/ci.yml`): pytest SQLite + PostgreSQL,
  build do frontend, e2e com simulador da OpenRouter, testes de montagem com o ffmpeg 7 do Debian →
  publica `ghcr.io/dhqdev/dark-model:latest` (amd64 + **arm64**). Leva ~10 min.
- Produção: VPS Oracle **ARM64** com Portainer (Swarm + Traefik, `dark.tekvosoft.com`), stack
  `deploy/portainer-swarm-traefik.yml` com serviços `api` e `worker`. Depois do CI verde, diga a ele
  para clicar **Update the stack** com **Re-pull image** marcado e repetir a ação.
- Antes de subir: `cd backend && python -m pytest -q` e `cd frontend && npm run build`.
  Mudou `montage.py`/`media.py`? Rode `tests/test_render.py`. Mudou modelo do banco? Crie migração
  (o teste `test_migrations.py` compara migrações × models e falha se divergirem).
- Textos da interface, mensagens de erro e comentários do código são em **português**.
  Prompts para a IA são em inglês (com campos explicativos pedidos em pt-BR).

## Mapa do código

```
backend/app/
  main.py          FastAPI: /api/*, guarda CSRF (header X-Requested-With: dark-model), serve o SPA
  cli.py           papéis da imagem: api | worker | all (api+worker) | migrate  (python -m app <papel>)
  config.py        Settings (variáveis de ambiente)          db.py  engine/sessões (SQLite ou Postgres)
  models.py        Channel, Skill, SkillLearning, FeedbackEvent, Project, Scene, Asset,
                   ThumbnailConcept, Job, UsageRecord, AppSetting, CatalogEntry, WorkerHeartbeat
  api/             rotas REST (projects, scenes, channels, thumbnails, jobs, usage, settings, assets…)
  serialize.py     model → JSON da API (formato consumido por frontend/src/lib/types.ts)
  jobs/            queue.py (fila no banco, lanes, grupos, retry, GROUP_HOOKS), worker.py, context.py
  pipeline/        uma etapa por arquivo; cada handler é @handler("tipo.do.job")
    script.py      script.analyze         scenes.py   scenes.plan / scene.rewrite
    visuals.py     visual.image → visual.motion | visual.video
    narration.py   narration.scene (→ visual.motion ajustado ao áudio) / narration.merge
    render.py      render.final (vídeo final; dispara sozinho via GROUP_HOOKS)
    thumbnail.py   thumbnail.concepts → thumbnail.image      metadata.py  metadata.generate
    export.py      export.zip (→ skill.learn)                learning.py  skill.draft/learn/consolidate
    estimate.py    estimativa de custo + Planner do teto em R$ (plano salvo em Project.plan)
    prompts.py     TODOS os prompts       schemas.py  respostas JSON (Lenient: tolera nomes/formatos)
    llm.py         call_json: schema estrito + 1 nova tentativa se o JSON vier inválido
    text.py        frases, WPM por idioma, hashes, SRT      files.py  uso de disco/exclusão por parte
    common.py      model_for, hashes de "desatualizado", save_asset, StageError
  providers/       openrouter.py (LLM/Image/TTS/Video), local.py (ffmpeg), registry.py
  tiers.py         níveis ECONOMY/BALANCED/PREMIUM, TIER_PARAMS, escolha automática de modelos
  catalog.py       catálogo/preços da OpenRouter em cache (tabela catalog_entries)
  pricing.py       custo por imagem/TTS/vídeo/tokens     usage.py  livro-caixa, limites de gasto
  montage.py       montagem do vídeo final (xfade, drawtext máquina de escrever, mixagem)
  media.py         ffmpeg/ffprobe, movimento Ken Burns, MP3     sfx.py  efeitos sonoros sintetizados
  fx.py            cotação USD→BRL     storage.py  arquivos em DATA_DIR/storage     security.py  login
backend/alembic/versions/   0001 inicial · 0002 Project.plan · 0003 transition/sfx/overlay_text
backend/tests/              pytest + fake_openrouter.py (simulador da API inteira)
frontend/src/               React 19 + Vite + Tailwind 4 + TanStack Query + react-router
  pages/Project.tsx + pages/project/*Stage.tsx   abas do projeto (Roteiro … Arquivos)
  lib/api.ts  lib/types.ts  lib/format.ts        components/ (ui, jobs, estimate, ChannelForm…)
deploy/                     stacks Portainer     Dockerfile  frontend build + python:3.12-slim + ffmpeg
```

## Conceitos que mandam no código

- **Tudo que é pesado é um Job** (`jobs/queue.py`). A API só enfileira e devolve o job; o worker
  executa o handler registrado. Cada tipo tem uma *lane* (`LANES`: llm, image, tts, video, cpu) e um
  *stage*. Lotes = job-grupo (`create_group`) com filhos; "Repetir" refaz só filhos que falharam.
  `FREE_KINDS` não passam pelo limite de gasto. Tipo novo ⇒ registre em `LANES` e `STAGES`.
- **Encadeamento:** handlers chamam `ctx.follow_up(...)` (ex.: imagem → movimento). Quando um grupo
  termina com sucesso rodam os `queue.GROUP_HOOKS` (ex.: `render._auto_render` monta o vídeo final).
- **"Desatualizado" por hash:** cada Asset guarda `source_hash` das entradas (`visual_hash`,
  `clip_hash`, `audio_hash` em `pipeline/common.py`). Mudar prompt/voz/tipo invalida só o que
  depende disso; `*_state()` diz o que está pronto e os enqueue agendam só o que falta.
- **Cena aponta para o asset escolhido** (`image_asset_id`, `clip_asset_id`, `audio_asset_id`);
  versões antigas ficam guardadas (aba Arquivos → "Versões antigas").
- **Custos:** toda chamada paga grava um `UsageRecord` via `ctx.record(...)` com o custo real da
  OpenRouter. Estimativas nunca inventam número (sem dado → "—").
- **Plano dentro do teto:** `estimate.production_plan()` escolhe modelo de texto/imagem/voz, segundos
  por cena, % de vídeo IA e nº de thumbnails que cabem no `cap_brl` do nível; as etapas leem do plano
  (`plan_model`, `planned`). Modelos fixados em Configurações nunca são trocados.
- **Skill do canal:** contexto de toda chamada de IA = canal + Skill atual + aprendizados aceitos
  (`pipeline/context.py`). Ações do usuário viram `FeedbackEvent`; exportar dispara `skill.learn`.
- **Erros:** `StageError` = erro explicável ao usuário (não repete). `ProviderError(retryable=…)`
  para a OpenRouter (429/5xx repetem; 402 saldo e moderação param).

## Receitas rápidas (detalhes em `docs/receitas.md`)

- **Nova coluna:** `models.py` + nova migração `backend/alembic/versions/000N_*.py` (use
  `batch_alter_table` e `server_default` para funcionar no SQLite) + `serialize.py` + `types.ts`.
- **Novo job/etapa:** handler `@handler("x.y")` em `pipeline/`, importe o módulo em
  `pipeline/handlers.py`, `LANES`/`STAGES` em `jobs/queue.py`, rota em `api/`, botão na aba.
- **Mudar o que a IA gera:** prompt em `pipeline/prompts.py` + campo em `pipeline/schemas.py`
  (classe `Lenient`, adicione `ALIASES` para nomes alternativos) + simulador em `tests/fake_openrouter.py`.
- **Mudar níveis/preços padrão:** `tiers.py` (`TIER_PARAMS`, `PREFERRED`) e o README.

## Armadilhas já conhecidas

- **ffmpeg 7** (imagem Docker, Debian) é mais rígido que o do Ubuntu do CI: `xfade` exige fps
  constante (pôr `fps=` depois de `setpts`), `filter_complex_script` está obsoleto. Teste com o job
  `ffmpeg-image` do CI.
- Etapas longas de ffmpeg precisam de `ctx.keepalive()` ou `ctx.progress()`; sem sinal de vida por
  `JOB_STALE_SECONDS` (300 s) o job é considerado travado e reenfileirado.
- `llm.strict_schema` remove `title`/`default` do JSON Schema, **mas não dentro de `properties`**
  (um campo pode se chamar `title`). Modelos às vezes devolvem campos com outro nome → `ALIASES`.
- Gemini TTS só devolve PCM: `providers/openrouter.py` pede `pcm` e converte para MP3 (24 kHz).
- Servidor é ARM e pequeno: cuidado com paralelismo de ffmpeg (`WORKER_LANES cpu=…`).
- Sem gastar dinheiro: `python -m tests.fake_openrouter --port 9911` + `OPENROUTER_BASE_URL`.

## Mais detalhes

- `docs/arquitetura.md` — processos, fila, banco, storage, segurança
- `docs/pipeline.md` — cada etapa: entrada, saída, jobs, gatilhos e regras
- `docs/custos-e-modelos.md` — níveis, escolha de modelos, estimativa, teto, livro-caixa
- `docs/frontend.md` — telas, abas do projeto, como os dados chegam
- `docs/api.md` — todas as rotas REST
- `docs/receitas.md` — passo a passo das mudanças mais comuns e como testar/deployar
- `docs/historico.md` — o que já foi feito e decisões tomadas
