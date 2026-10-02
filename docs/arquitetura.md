# Arquitetura

## Processos

Uma única imagem Docker (`Dockerfile`) com quatro papéis, escolhidos pelo argumento de
`python -m app <papel>` (`backend/app/cli.py`):

| Papel | O que faz |
|---|---|
| `api` (padrão) | aplica as migrações (cria o banco no Postgres se faltar) e sobe o uvicorn na porta 8000 |
| `worker` | espera o schema existir e roda `jobs.worker.Worker.run_forever()` |
| `all` | API + worker na mesma thread (`EMBEDDED_WORKER=true`) — dev e instalação mínima |
| `migrate` | só migrações |

Em produção (`deploy/portainer-swarm-traefik.yml`) rodam dois serviços: `api` e `worker`, ambos com o
volume `/data` (storage) e o PostgreSQL já existente na VPS (`postgres_postgres`, banco `darkmodel`).

```
Navegador (React SPA) ──cookie dm_session──▶ API FastAPI (/api/*) ──▶ PostgreSQL ◀── Worker(s)
                                              serve frontend/dist             │
                                                                              ├─ OpenRouter (LLM, imagem, TTS, vídeo)
                                                                              └─ ffmpeg local (movimento, montagem, áudio, ZIP)
                                                                              ▼
                                                                    /data/storage/projects/<id>/…
```

## Aplicação web (`main.py`)

- Rotas em `backend/app/api/*.py`, todas com prefixo `/api`. Dependência `require_user` (`deps.py`)
  exige o cookie de sessão; `get_db` dá a sessão SQLAlchemy.
- **CSRF:** toda requisição POST/PUT/PATCH/DELETE em `/api/` precisa do header
  `X-Requested-With: dark-model` (o `frontend/src/lib/api.ts` sempre manda).
- CSP restrita (`script-src 'self'`) no HTML; nada de scripts externos no frontend.
- `/api/docs` (Swagger) só fora de produção (`APP_ENV`).
- Ao subir: com chave da OpenRouter, aquece o catálogo em segundo plano.

## Banco (`models.py`, `db.py`, Alembic)

- SQLite (dev/testes, `DATA_DIR/dark-model.db`) ou PostgreSQL (`DATABASE_URL` ou `POSTGRES_*`).
- Datas sempre UTC sem fuso (`utcnow()`).
- Migrações em `backend/alembic/versions/` numeradas `0001`, `0002`… com `revision = '000N'`.
  `tests/test_migrations.py` exige que `upgrade head` gere exatamente o schema dos models.

Entidades:

| Tabela | Papel |
|---|---|
| `channels` | idioma, público, nicho, estilo, tom, duração alvo, WPM, `scene_seconds`, estilo visual, voz (`tts_model/voice/speed/style`), estilo de thumbnail, nível padrão |
| `skills` | versões da Skill (Markdown) do canal; a maior `version` é a atual |
| `skill_learnings` | aprendizados `proposed / accepted / rejected / merged` |
| `feedback_events` | sinais do usuário (prompt editado, tipo trocado, título escolhido, thumbnail favorita…) |
| `projects` | roteiro, `analysis` (JSON), hashes do roteiro analisado/dividido, `plan` (plano de custo), metadados escolhidos, `status` draft→script→scenes→production→ready→exported |
| `scenes` | narração, duração estimada/real, descrição visual (pt-BR), `prompt` (inglês), `asset_type` IMAGE / IMAGE_MOTION / VIDEO, `motion`, `transition`, `sfx`, `overlay_text`, `locked`, ids dos assets escolhidos |
| `assets` | todo arquivo gerado: `kind` image/video/motion/audio/narration/thumbnail/export/final, caminho, modelo, custo, `source_hash` |
| `thumbnail_concepts` | ideia, emoção, composição, texto, prompt, asset escolhido |
| `jobs` | fila (ver abaixo) |
| `usage_records` | livro-caixa de cada chamada paga (tokens, unidades, `cost_usd`, `cost_source`) |
| `app_settings` | chave→JSON: `tiers` (config por nível), `budget` (limites), `fx` (cotação) |
| `catalog_entries` | cache do catálogo da OpenRouter |
| `worker_heartbeats` | workers online (o painel avisa "nenhum worker online") |

## Fila de jobs (`jobs/`)

- `queue.enqueue(db, kind, …)` cria um job `queued` (com `dedupe=True` não duplica um job ativo
  igual). `create_group` cria um job-grupo (`is_group=True`); filhos têm `parent_id`.
- `LANES` mapeia cada tipo para uma vaga: `llm`, `image`, `tts`, `video`, `cpu` (ffmpeg). O worker
  tem N vagas por lane (`WORKER_LANES`, padrão `llm=2,image=4,tts=3,video=2,cpu=1`).
- `claim` reserva atomicamente (`SKIP LOCKED` no Postgres, UPDATE condicional no SQLite).
- `worker.execute` → checa limite de gasto (exceto `FREE_KINDS`) → roda o handler → `finish`.
  Exceções: `CanceledError` → canceled; `StageError`/`BudgetExceeded` → failed sem retry;
  `ProviderError` → failed, com retry automático com backoff se `retryable`; `MediaError` → failed.
- `update_group` recalcula progresso/estado do grupo e, quando ele vira `succeeded`, roda os
  `GROUP_HOOKS` (hoje: `render._auto_render`).
- `retry` de um grupo reenfileira só os filhos com erro. `cancel` marca `cancel_requested`; o handler
  percebe em `ctx.progress()`/`ctx.check_cancel()`.
- `recover_stale`: job `running` sem heartbeat por `JOB_STALE_SECONDS` (300 s) volta para a fila.
  Por isso etapas longas usam `ctx.keepalive()`.
- O worker também concilia custos `pending` de TTS (`usage.reconcile_pending`, via `/generation`).

`JobContext` (`jobs/context.py`) entrega ao handler: `payload`, ids (`project_id`, `scene_id`,
`target_id`…), `progress()`, `keepalive()`, `check_cancel()`, `record()/record_now()` (livro-caixa) e
`follow_up()` (enfileira o próximo job no mesmo grupo).

Padrão de um handler: ler o que precisa numa `session_scope()` curta, **fechar a sessão** durante a
chamada à IA/ffmpeg, abrir outra para gravar o resultado (`save_asset`, atualizar a cena).

## Providers (`providers/`)

- `base.py`: protocolos `LLMProvider`, `ImageProvider`, `TTSProvider`, `VideoProvider`, `Usage`,
  `ProviderError(retryable, status)`.
- `openrouter.py`: cliente HTTP com retry em 429/5xx; `OpenRouterLLM` (chat com structured outputs,
  reasoning), `OpenRouterImage` (endpoint de imagens ou chat com modalidade imagem),
  `OpenRouterTTS` (`/audio/speech`; aprende o formato aceito por modelo; Gemini só PCM → MP3),
  `OpenRouterVideo` (`/videos` com polling, imagem como primeiro quadro).
- `local.py`: movimento Ken Burns com ffmpeg (`ffmpeg-kenburns`, custo zero).
- `registry.py`: referências `provider:modelo` (`split_ref`), fábrica por modalidade e
  `configure_for_tests` (injeta o `MockTransport` do simulador).

## Storage (`storage.py`)

`LocalStorage` em `DATA_DIR/storage`. Caminhos relativos tipo
`projects/<id>/scenes/<scene_id>/image-<data>-<hex>.jpg` (`common.new_asset_path`). Arquivos só são
servidos autenticados por `GET /api/assets/{id}/file`.

## Segurança (`security.py`, `api/auth.py`)

Login único (`APP_USERNAME`/`APP_PASSWORD`), cookie JWT HS256 `dm_session` HttpOnly SameSite=Lax
(`Secure` com `COOKIE_SECURE=true`); a impressão digital da senha vai no token (trocar a senha derruba
as sessões). Limite: 5 falhas em 10 min por IP. Chaves de API nunca vão para o frontend.
