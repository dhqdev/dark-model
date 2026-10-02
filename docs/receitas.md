# Receitas (como fazer as mudanças mais comuns)

## Ambiente local rápido

```bash
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q                                  # suíte completa (SQLite)
.venv/bin/python -m pytest -q tests/test_render.py             # montagem com ffmpeg
cd ../frontend && npm ci && npm run build                      # tipos + build
```

Sistema inteiro sem gastar: `python -m tests.fake_openrouter --port 9911 &` e
`OPENROUTER_BASE_URL=http://127.0.0.1:9911/api/v1 OPENROUTER_API_KEY=fake APP_USERNAME=admin
APP_PASSWORD=x python -m app all`; `scripts/seed_demo.py --url http://127.0.0.1:8000 --password x` cria canal + projeto completo.

## Entregar (deploy)

1. Commit direto na branch `default` e `git push -u origin default` (autorizado pelo dono).
2. CI ~10 min → `ghcr.io/dhqdev/dark-model:latest`. Se ficar vermelho, corrigir antes de avisar.
3. Avisar (pt-BR): no Portainer, stack do Dark Model → **Update the stack** com **Re-pull image** e
   depois repetir a ação na plataforma.

## Adicionar um campo no banco

1. `backend/app/models.py`: nova coluna (com `default=` e, se NOT NULL, `server_default=`).
2. Nova migração `backend/alembic/versions/000N_descricao.py` (`revision='000N'`,
   `down_revision` = anterior) usando `op.batch_alter_table` (SQLite). Veja `0003_scene_edit.py`.
3. `tests/test_migrations.py` precisa passar (migração == model, tipos inclusos).
4. Expor: `serialize.py` → `frontend/src/lib/types.ts` → tela. Aceitar edição: schema Pydantic da
   rota em `api/*.py` (`PATCH`).

## Adicionar uma nova etapa / tipo de job

1. Handler em `backend/app/pipeline/<etapa>.py`:
   ```python
   @handler("minha.etapa")
   def minha_etapa(ctx: JobContext) -> dict:
       with session_scope() as db:      # lê o que precisa
           project = load_project(db, ctx.project_id)
           model = plan_model(db, project, "text")
       ctx.progress(0.2, "fazendo…", force=True)
       result, _ = call_json(ctx, model=model, system=..., user=..., schema=MeuSchema, schema_name="meu")
       with session_scope() as db:      # grava o resultado
           ...
       return {"message": "pronto"}
   ```
2. Importe o módulo em `pipeline/handlers.py`.
3. `jobs/queue.py`: `LANES["minha.etapa"]` e `STAGES["minha.etapa"]`; se for local/grátis, inclua
   em `FREE_KINDS`.
4. Rota em `api/projects.py` (ou outra) que valida e chama `queue.enqueue(...)` + `db.commit()`.
5. Botão na aba (`useProjectAction(project.id, "minha-rota")`) e estado em `stage_summary` se precisar.
6. Teste em `backend/tests/` usando as fixtures `client`, `auth`, `fake` e `run_until_idle()`.
7. Se chama a OpenRouter com um formato novo, ensine o `tests/fake_openrouter.py` a responder.

## Mudar o que a IA gera (prompt / campos)

- Prompts: `pipeline/prompts.py` (uma função por chamada, retorna `(system, user)`).
- Formato: `pipeline/schemas.py`. Herdar de `Lenient` (aceita nomes alternativos via `ALIASES`,
  listas vindas como texto, valores fora do enum normalizados). Novos enums: tuplas no topo
  (`TRANSITIONS`, `SFX`…) + rótulos em `frontend/src/lib/format.ts`.
- O simulador (`tests/fake_openrouter.py → _chat`) reconhece cada chamada por palavras do prompt
  (ex.: `SENTENCES` → `scene_plan`, `titles:` → `video_metadata`) e devolve respostas fixas: ao mudar
  o prompt ou criar campo novo, atualize essas palavras e as respostas, senão testes e e2e quebram.

## Efeitos do vídeo final

- Nova transição: `TRANSITIONS` em `montage.py` (nome → xfade do ffmpeg + duração),
  `schemas.TRANSITIONS` (+ aliases), `TRANSITION_LABEL` no frontend, e o prompt de cenas.
- Novo efeito sonoro: `sfx.py` (síntese) + `schemas.SFX` + `SFX_LABEL`.
- Sempre rodar `tests/test_render.py` e lembrar do ffmpeg 7 da imagem (fps constante antes do xfade).
- Mudou a lógica de montagem de forma que vídeos antigos devam ser refeitos? Incremente
  `RENDER_VERSION` em `pipeline/render.py`.

## Mudar níveis, modelos, custo

- Padrões: `tiers.TIER_PARAMS` (resolução, % vídeo, mínimo por cena, teto R$) e `tiers.PREFERRED`
  (regex de famílias por nível). Atualize a tabela do README.
- Ordem de cortes do planejador: `estimate.PENALTY` e `_options`.
- O usuário pode fixar tudo pela tela Configurações — prefira orientar isso quando for preferência.

## Problemas comuns em produção

| Sintoma | Onde olhar |
|---|---|
| Job "travado" e reiniciando | falta `ctx.progress`/`ctx.keepalive` numa etapa longa (`JOB_STALE_SECONDS`) |
| Erro ffmpeg só no servidor | diferença ffmpeg 7 (Debian) × CI; job `ffmpeg-image` do CI |
| JSON inválido da IA | `llm.call_json` (1 nova tentativa), `schemas.Lenient`/`ALIASES`, `strict_schema` |
| Modelo não encontrado | catálogo desatualizado → `POST /api/catalog/refresh` ou fixar modelo |
| TTS sem áudio/formato | `OpenRouterTTS._format_for` / `_PCM_ONLY` |
| Custo "—" | modelo sem preço publicado; preenchido após 1ª geração (histórico) |
