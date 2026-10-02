# Custos, níveis e escolha de modelos

## Níveis (`backend/app/tiers.py`)

`Quality`: `ECONOMY`, `BALANCED` (padrão), `PREMIUM`. Cada projeto tem um nível (`project.quality`;
padrão vem do canal). Operações: `text`, `image`, `thumbnail`, `tts`, `video`.

- `TIER_PARAMS` — padrões por nível: `image_resolution`, `video_resolution`, `thumb_concepts`,
  `thumb_variations`, `video_share` (fração de cenas com vídeo IA), `reasoning`, `min_scene_seconds`,
  `cap_brl` (teto por vídeo em R$; 0 = sem teto). Hoje: Economy 1K/sem vídeo/12 s/sem teto;
  Balanced 1K/3%/9 s/R$ 20; Premium 2K/10%/sem mínimo/R$ 50.
- Configurações do usuário ficam em `app_settings["tiers"]` e se sobrepõem aos padrões
  (`get_tier_settings` / `save_tier_settings`, tela Configurações → `PUT /api/settings/tiers`).
  Um modelo configurado ali (`cfg[op]`) é **fixo**: nunca trocado pelo planejador.
- `resolve_model(db, op, tier)`: configurado → senão regex de `PREFERRED[op][tier]` sobre o catálogo
  (texto/TTS: versão mais nova; imagem/thumbnail/vídeo fora do Premium: a mais barata com preço real,
  `PRICE_FIRST`) → senão `_auto_pick` por faixa de preço (Economy mais barato, Premium mais caro,
  Balanced mediana). Sem nada → `StageError` "Nenhum modelo disponível…".

## Catálogo (`catalog.py`)

Busca na OpenRouter `/models` (texto), modelos de imagem e seus `/endpoints` (preço), `/videos/models`,
vozes de TTS. Cache em memória (60 s) + tabela `catalog_entries` (validade `CATALOG_TTL_MINUTES`,
padrão 360). `POST /api/catalog/refresh` força atualização. Helpers: `model_info`, `image_caps`,
`video_model`, `speech_voices`, `exists`.

## Preços (`pricing.py`)

- `llm_cost` por tokens (preço do catálogo).
- `image_cost`: preço por imagem do endpoint ou tokens por imagem (`TOKENS_PER_IMAGE` por
  resolução) ou média histórica do próprio uso (`history_unit_cost`).
- `tts_cost`: por caractere/segundo ou tokens de áudio (`AUDIO_TOKENS_PER_SECOND`).
- `video_cost`: SKUs de preço por segundo/resolução (`video_skus_cost`), duração/resolução válidas
  do modelo (`video_duration_for`, `video_resolution_for`).
- Cada valor carrega a origem (`Cost.source`): catálogo ●, histórico ◆, aproximado ≈, local ○,
  desconhecido — (sem número inventado).

## Estimativa e plano dentro do teto (`pipeline/estimate.py`)

- `project_inputs`: segundos estimados (roteiro × WPM), nº de cenas, caracteres de narração, cenas de
  vídeo já planejadas (e travadas) etc.
- `Planner` monta opções por componente, sempre do melhor para o mais barato:
  imagens (modelo do nível → modelos dos níveis abaixo), texto, TTS (voz do canal fixa não muda),
  thumbnails (menos variações → níveis abaixo), segundos por cena (base → 9/12 → 15/18/20 s) e
  % de vídeo (cheio → metade → zero). Antes das cenas existirem varia a duração das cenas; depois,
  varia quantas cenas de vídeo IA ficam.
- `fit_tier` testa todas as combinações e escolhe a de **menor penalidade** (`PENALTY`: perder imagem
  e voz pesa mais; vídeo e thumbnail pesam menos) que cabe em `cap_brl / cotação`. Se nenhuma cabe,
  usa a mais barata e avisa. Devolve linhas, total US$/R$, ajustes em texto e o `plan`.
- `estimate_project` → os três níveis lado a lado (`GET /api/projects/{id}/estimate`).
- `production_plan(project)` grava o plano em `project.plan` (com hash da config do nível) e o
  reaproveita; é recalculado ao planejar cenas, ao gerar visuais em lote, ao trocar o nível ou a
  config. `_pins`: modelos de imagem/voz que já geraram assets no projeto continuam.
- Etapas leem o plano: `plan_model(db, project, op)` e `planned(project, key)`.
- O teto vale para o **plano**; refazer cenas pode passar dele. Limite rígido = limites de gasto.

## Custo real e livro-caixa (`usage.py`)

- Providers devolvem `Usage` (tokens, unidades, `cost_usd`, `generation_id`). Handlers chamam
  `ctx.record(db, usage, ...)` → linha em `usage_records` com job/canal/projeto/cena/etapa.
- `cost_source`: `reported` (veio em `usage.cost`), `generation` (consultado em `/generation`),
  `pending` (TTS: a OpenRouter ainda não tinha o custo; o worker concilia com `reconcile_pending`),
  `free`, `unknown`.
- Agregações: `by_stage`, `by_model`, `project_costs`, `summary` (por dia, canal, total) — telas
  Consumo e Custos do projeto (`GET /api/usage/summary`, `/api/projects/{id}/costs`).
- Limites (`app_settings["budget"]`: diário e por projeto, em US$): `check_budget` antes de cada job
  pago → `BudgetExceeded` falha o job com mensagem clara.
- Saldo: `GET /api/usage/balance` (`/credits` com `OPENROUTER_MANAGEMENT_KEY`, senão limite da chave).

## Câmbio (`fx.py`)

Cotação USD→BRL do dia (AwesomeAPI, Frankfurter de reserva), guardada em `app_settings["fx"]` por
12 h; falhou → última cotação ou `USD_BRL` (5,5). `FX_AUTO=false` ou cotação manual em Configurações
(`PUT /api/settings/fx`) fixam o valor. Tetos são em R$; a OpenRouter cobra em US$.
