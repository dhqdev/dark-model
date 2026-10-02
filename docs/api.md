# Rotas da API (`backend/app/api/`)

Todas sob `/api`, exigem login (cookie) exceto `health` e `auth/*`. Requisições que alteram dados
exigem o header `X-Requested-With: dark-model`. Rotas que geram algo devolvem o job criado
(`_job_out`) e o trabalho acontece no worker.

| Arquivo | Rotas |
|---|---|
| `system.py` | `GET /health` · `GET /system/status` (workers online, fila, chaves configuradas) |
| `auth.py` | `GET /auth/status` · `POST /auth/login` · `POST /auth/logout` · `GET /auth/me` |
| `dashboard.py` | `GET /dashboard` (projetos recentes, gastos, uso de disco, jobs) |
| `channels.py` | `GET/POST /channels` · `GET/PATCH/DELETE /channels/{id}` · Skill: `GET/PUT /channels/{id}/skill`, `GET …/skill/{version}`, `POST …/skill/restore/{version}`, `POST …/skill/draft`, `POST …/skill/consolidate` · Aprendizados: `GET/POST /channels/{id}/learnings`, `PATCH/DELETE /channels/learnings/{id}` · Voz: `GET /channels/{id}/voices`, `POST /channels/{id}/voice-preview` (devolve áudio + custo) |
| `projects.py` | `GET/POST /projects` · `GET/PATCH/DELETE /projects/{id}` · `POST …/analyze` · `POST …/scenes/plan` · `POST …/visuals` · `POST …/narration` · `POST …/narration/merge` · `POST …/thumbnails` · `POST …/metadata` · `POST …/export` · `POST …/render` · `POST …/autopilot` (start/stop do piloto automático) · `GET …/storage` · `DELETE …/storage/{part}` · `POST …/learn` · `GET …/estimate` · `GET …/costs` · `GET …/jobs` · `GET …/exports` |
| `scenes.py` | `PATCH/DELETE /scenes/{id}` · `POST …/rewrite` · `POST …/visual` · `POST …/narration` · `GET …/assets` (versões) · `POST …/select` (escolhe versão) |
| `thumbnails.py` | `PATCH/DELETE /thumbnails/{id}` · `POST …/generate` (mais uma variação) · `POST …/select` |
| `assets.py` | `GET /assets/{id}/file` (download autenticado) · `DELETE /assets/{id}` |
| `jobs.py` | `GET /jobs` · `GET /jobs/{id}` · `POST /jobs/{id}/retry` · `POST /jobs/{id}/cancel` |
| `usage.py` | `GET /usage/summary` · `GET /usage/balance` · `GET /usage/records` |
| `settings.py` | `GET /settings` · `PUT /settings/tiers` · `PUT /settings/budget` · `PUT /settings/fx` · `GET /catalog/{kind}` · `GET /catalog/image/price` · `POST /catalog/refresh` · `POST /settings/test-openrouter` |

`GET /projects/{id}` é a rota central da tela do projeto: devolve o projeto, as cenas serializadas
com estado (`visual_ready`, `image_ok`, `audio_ok`…), conceitos de thumbnail, custos, jobs ativos e
`stages` (resumo de cada aba, calculado em `projects.stage_summary`). O JSON é montado em
`serialize.py`; os tipos equivalentes no frontend estão em `frontend/src/lib/types.ts` — mude os dois
juntos.
