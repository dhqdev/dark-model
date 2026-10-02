# Frontend (`frontend/`)

React 19 + Vite + Tailwind 4 + TanStack Query + react-router 8, TypeScript. Interface toda em pt-BR,
visual escuro "estúdio" (fontes Fraunces, IBM Plex Sans/Mono; estilos em `src/index.css`).
Em produção o FastAPI serve `frontend/dist`; em dev, `npm run dev` (porta 5173) faz proxy de `/api`
para a 8000.

## Rotas (`src/App.tsx`)

| URL | Página | O quê |
|---|---|---|
| `/` | `pages/Dashboard.tsx` | resumo: projetos recentes, gasto do dia/mês, saldo, disco, fila |
| `/canais` | `pages/Channels.tsx` | lista e criação de canais |
| `/canais/:channelId` | `pages/ChannelDetail.tsx` | configuração (`components/ChannelForm.tsx`), testar voz, Skill (versões, diff, restaurar, IA), aprendizados, projetos do canal |
| `/projetos/:projectId` | `pages/Project.tsx` | o projeto, com abas (abaixo) |
| `/fila` | `pages/Queue.tsx` | jobs: progresso, repetir, cancelar |
| `/consumo` | `pages/Usage.tsx` | custos por etapa/modelo/canal/dia (`components/DailyChart.tsx`) |
| `/ajustes` | `pages/Settings.tsx` | modelos por nível e operação, teto, limites de gasto, cotação, catálogo, teste da chave |
| `/login` | `pages/Login.tsx` | login único (`lib/auth.tsx`) |

`components/Layout.tsx` = menu lateral/inferior (celular) + indicador de worker/fila.

## Tela do projeto (`pages/Project.tsx`)

Abas pela query `?etapa=` (`STAGES`): `roteiro`, `cenas`, `visuais`, `narracao`, `video`,
`thumbnail`, `metadados`, `exportacao`, `custos`, `arquivos`. Cada aba é um componente em
`pages/project/`:

| Aba | Componente | Usa |
|---|---|---|
| Roteiro | `ScriptStage.tsx` | editar roteiro, análise, estimativa dos 3 níveis (`components/estimate.tsx`) |
| Cenas | `ScenesStage.tsx` | dividir, editar cena (prompt, tipo, motion, transição, sfx, texto), reescrever, travar |
| Visuais | `VisualsStage.tsx` | gerar faltantes/todas, por cena, escolher versões |
| Narração | `NarrationStage.tsx` | narrar, ouvir por cena, narração completa |
| Vídeo final | `VideoStage.tsx` | checklist, montar de novo, assistir/baixar |
| Thumbnail | `ThumbnailStage.tsx` | conceitos, imagens, favorita |
| Título/Desc. | `MetadataStage.tsx` | títulos, descrição, capítulos, tags |
| Exportação | `ExportStage.tsx` | gerar/baixar ZIP |
| Custos | `CostsStage.tsx` | custo real por etapa (`StageCostTable`) |
| Arquivos | `FilesStage.tsx` | uso de disco por parte e exclusão |

O cabeçalho mostra status, nível (trocar nível refaz o plano), tamanho e custo; cada aba tem um
indicador de estado vindo de `project.stages` (`stageInfo`). Entre o cabeçalho e as abas fica o
**piloto automático** (`pages/project/Autopilot.tsx`): etapas ✓/▸, ligar/parar/retomar, aviso de pausa.
A aba Custos tem o quadro **Planejado × real** por etapa (plano do nível atual × custo cobrado).

## Dados

- `lib/api.ts`: `api.get/post/put/patch/del` sobre `fetch('/api…')`, sempre com
  `X-Requested-With: dark-model`; 401 dispara o evento `dm:unauthorized` (volta ao login);
  `errorMessage(err)` extrai o `detail` do FastAPI.
- `lib/types.ts`: tipos espelhando `backend/app/serialize.py` (mude os dois juntos).
- `lib/format.ts`: `usd`, `brl`, `timecode`, `bytes`… e rótulos pt-BR (`QUALITY_LABEL`,
  `TRANSITION_LABEL`, `SFX_LABEL`, `MOTION_LABEL`, `PROJECT_STATUS`, `LANGUAGES`).
- `pages/project/shared.ts`: `useProjectAction(projectId, path, okText)` = POST
  `/projects/{id}/{path}` + toast + invalida a query `["project", id]`.
- Query principal: `["project", id]` → `GET /projects/{id}`, refetch a cada 2 s enquanto
  `active_jobs` não está vazio.
- UI reutilizável em `components/ui.tsx`: `Panel`, `Btn`, `Field`, `Badge`, `Led`, `Meter`, `Stat`,
  `Segmented`, `Modal`, `Empty`, `Loading`, `ErrorBox`, `Notice`, `SourceMark` (●◆≈○—), `useToast`,
  `MarkdownView`, `LineDiff`. Jobs: `components/jobs.tsx` (`JobLine`, `useJobActions`).

## Testes

`npm run build` roda `tsc --noEmit` + build (é o que o CI exige). `npm run test:e2e`
(`e2e/smoke.mjs`, Playwright) navega por todas as telas em desktop e celular contra o sistema
rodando com o simulador; se você muda textos/rotas que o smoke procura, ajuste o smoke.
