# Pipeline de produção

Cada etapa = um (ou mais) tipo de job com handler em `backend/app/pipeline/`. A rota da API valida,
enfileira e devolve o job; a tela acompanha pelo `GET /api/projects/{id}` (refaz a consulta a cada 2 s
enquanto há jobs ativos).

Contexto de IA comum (`pipeline/context.py → full_context`): bloco do canal (idioma, público, nicho,
estilo, tom, duração…) + Skill atual + aprendizados aceitos + dados do projeto. Todas as chamadas de
texto usam `llm.call_json` com um schema de `pipeline/schemas.py` e um prompt de `pipeline/prompts.py`.
O modelo de texto vem do plano do projeto (`plan_model(db, project, "text")`).

## 01 Roteiro — `script.analyze` (`script.py`)

- Rota: `POST /projects/{id}/analyze` (mínimo 30 palavras).
- `text.script_metrics`: palavras, duração estimada pelo WPM do idioma (`text.LANG_WPM`), frases e
  trechos de 5 palavras repetidos, frases longas.
- IA (`ScriptAnalysis`): notas, problemas com trecho/correção, riscos de política do YouTube,
  melhorias, `verdict` approved / needs_revision / high_risk. Explicações em pt-BR.
- Salva `project.analysis = {metrics, ai, model, created_at}` e `analysis_script_hash`
  (a análise fica "desatualizada" quando o roteiro muda).

## 02 Cenas — `scenes.plan`, `scene.rewrite` (`scenes.py`)

- Rota: `POST /projects/{id}/scenes/plan` (`replace=true` para substituir; apaga cenas e assets).
- O roteiro é dividido em frases **localmente** (`text.segment_script`); a IA só agrupa índices de
  frases em cenas — o texto da narração nunca é inventado nem perdido (`normalize_plan`).
- Roteiros longos vão em blocos de até 650 palavras (`chunk_segments`), passando a última descrição
  visual como continuidade.
- Duração alvo por cena e % de vídeo IA vêm do plano de custo (`production_plan(..., ignore_scenes=True)`).
  `limit_scene_count` junta cenas se a IA criar mais que 1,2× o esperado.
- Por cena a IA define: `visual_description` (pt-BR), `prompt` (inglês, fiel à narração; fotorrealista
  salvo se o estilo pedir ilustração — `prompts.wants_realism`), `asset_type` + motivo, `motion`,
  `transition` (1ª cena sempre dissolve), `sfx`, `overlay_text`. Valores normalizados por
  `schemas.norm_transition / norm_sfx / clean_overlay`.
- `scene.rewrite` (`POST /scenes/{id}/rewrite` com instrução) reescreve só uma cena usando as vizinhas
  como contexto e registra `FeedbackEvent`.
- Edição manual: `PATCH /scenes/{id}` (prompt, tipo, motion, transição, sfx, texto, narração, `locked`).
  Mudanças relevantes viram `FeedbackEvent`.

## 03 Visuais — `visual.image` → `visual.motion` | `visual.video` (`visuals.py`)

- Rotas: `POST /projects/{id}/visuals` (`scope`: missing/all, `scene_ids`) cria o grupo
  `visuals.batch`; `POST /scenes/{id}/visual` para uma cena.
- Antes do lote: `fit_video_scenes` refaz o plano e transforma em IMAGE_MOTION as cenas de vídeo que
  não cabem no teto (cenas `locked` ficam).
- `visual.image`: modelo/resolução do plano; imagem recortada para 1920×1080 JPEG; grava Asset `image`
  com `source_hash = visual_hash(prompt, estilo visual)`. Encadeia:
  - IMAGE_MOTION → `visual.motion` (lane cpu, ffmpeg Ken Burns, grátis, duração = áudio ou estimativa);
  - VIDEO → `visual.video` (vídeo IA usando a imagem como 1º quadro quando o modelo aceita);
  - IMAGE → nada (imagem parada).
- `scene_visual_state` diz `image_ok`, `clip_ok`, `ready`. `enqueue_scene_visual` agenda só o que falta.
- Versões antigas ficam; `POST /scenes/{id}/select` escolhe outra versão.

## 04 Narração — `narration.scene`, `narration.merge` (`narration.py`)

- Rotas: `POST /projects/{id}/narration` (grupo `narration.batch`), `POST /scenes/{id}/narration`,
  `POST /projects/{id}/narration/merge` (MP3 completo com `gap` entre cenas).
- Voz: `common.tts_settings` → modelo da voz do canal, senão do plano, senão do nível; voz inválida
  cai na primeira disponível com aviso.
- Texto > 3500 caracteres é partido (`split_for_tts`) e concatenado. Duração real medida (ffprobe)
  vai para `scene.audio_duration` — a partir daí a linha do tempo usa o áudio real.
- Se a cena tem clipe de movimento com duração diferente do áudio (> 0,3 s), re-renderiza o
  movimento (`visual.motion`, grátis).
- `source_hash = audio_hash(narração, modelo, voz, velocidade, estilo)`.

## 05 Vídeo final — `render.final` (`render.py` + `montage.py`)

- **Automático:** `GROUP_HOOKS` → `_auto_render` quando um `narration.batch` ou `visuals.batch`
  termina com sucesso, todas as cenas estão prontas e não há vídeo atual (ou ele está desatualizado).
- Manual: `POST /projects/{id}/render` (exige imagem e áudio em todas as cenas).
- `render_hash` = versão + tamanho/fps + (ids dos assets, tipo, motion, transição, sfx, texto) de cada
  cena; guardado em `asset.params.hash` para marcar o vídeo como desatualizado.
- Cada cena vira um `montage.Shot`: `video` (vídeo IA), `motion` (clipe ou gerado na hora), `still`.
  Sem vídeo IA pronto → usa imagem com movimento (aviso).
- `montage.build`: corpo de cada cena + pedaços de transição (`xfade`, tabela `TRANSITIONS`) codificados
  um a um em MP4 e juntados sem recodificar; texto com efeito máquina de escrever (`drawtext`, 17
  caracteres/s, som de teclas `sfx.render_typing`); efeitos sintetizados (`sfx.py`); narração na
  linha do tempo; fade de abertura/encerramento. Cenas > 12 s ganham um segundo enquadramento
  (punch-in 1,22×). Vídeo IA mais curto que o áudio continua com movimento do último quadro.
- Tolerante a falhas: transição com problema vira corte; cena com problema sai sem texto/efeito.
- Progresso real via `ffmpeg -progress` + `ctx.keepalive()`; cancelar mata o ffmpeg.
- Resultado: Asset `final` (MP4 H.264/AAC), baixado na aba "Vídeo final".

## 06 Thumbnail — `thumbnail.concepts` → `thumbnail.image` (`thumbnail.py`)

- Rota: `POST /projects/{id}/thumbnails` (grupo `thumbnail.batch`; `count`/`variations` opcionais,
  padrão do plano do nível).
- IA cria conceitos (nome, ideia, emoção, composição, texto curto no idioma do canal, prompt) usando
  títulos já escolhidos/sugeridos; cada conceito gera N imagens 1280×720.
- `channel.thumbnail_text_mode` decide se o texto vai dentro da imagem gerada.
- `POST /thumbnails/{id}/select` marca a favorita (FeedbackEvent).

## 07 Título/descrição — `metadata.generate` (`metadata.py`)

- Rota: `POST /projects/{id}/metadata`.
- IA (`VideoMetadata`): 8 títulos, corpo da descrição, capítulos (por posição de cena), tags,
  hashtags, palavras-chave, notas de política.
- `build_chapters` converte para os **tempos reais** da linha do tempo; `trim_tags` limita a ~480
  caracteres; `compose_description` junta corpo + capítulos + hashtags.
- Salva em `metadata_suggestions`; preenche `selected_title`, `description` e `tags` só se vazios.
- Edição/escolha: `PATCH /projects/{id}` (gera FeedbackEvent `title_selected`/`description_edited`).

## 08 Exportação — `export.zip` (`export.py`)

- Rota: `POST /projects/{id}/export`. ZIP com a estrutura do README (roteiro, cenas CSV/JSON, visuais
  na ordem, narração, SRT, thumbnails, metadados, `timeline.json`, `LEIA-ME.txt` para CapCut).
- Se o canal tem `auto_learn`, enfileira `skill.learn` no fim.

## Skill e aprendizados (`learning.py`)

- `skill.draft` (`POST /channels/{id}/skill/draft`): IA escreve a Skill a partir das configurações.
- `skill.learn`: lê `FeedbackEvent` não consumidos + resumo do projeto e propõe aprendizados.
- `skill.consolidate`: funde os aprendizados aceitos numa nova versão da Skill.
- Versões: `GET/PUT /channels/{id}/skill`, `…/skill/{version}`, `…/skill/restore/{version}`.

## Arquivos do projeto (`files.py`)

- `GET /projects/{id}/storage` → tamanho por parte (`PARTS`: analysis, scenes, images, motion,
  videos, narration, final, thumbnails, metadata, exports, old_versions, orphans).
- `DELETE /projects/{id}/storage/{part}` apaga a parte (bloqueia se houver job daquela parte rodando).
  O roteiro nunca é apagado por ali. Cada `Part` diz se refazer é `free`, `paid` ou `manual`.
