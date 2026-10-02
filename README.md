# Dark Model · Faceless Production Studio

Plataforma web para produzir vídeos **dark/faceless** para YouTube (15–25 min) em um só lugar:
canais com idioma, público e estilo próprios, uma **Skill** por canal que evolui com os projetos
aprovados, e um pipeline completo — roteiro, cenas, imagens/vídeos, narração, thumbnail, título e
descrição — com **custo real de cada etapa** e exportação organizada para o CapCut.

- **Single-user**, login por `APP_USERNAME` / `APP_PASSWORD` definidos na Stack.
- **OpenRouter** como gateway único de IA: texto, imagem, narração (TTS) e vídeo.
- **Docker + Portainer**, imagem publicada no GHCR pelo **GitHub Actions** (amd64 e **arm64**).

```
Canal ─┬─ Skill (versões + aprendizados aprovados)
       └─ Projeto ─┬─ 01 Roteiro      análise: estrutura, coerência, repetição, duração, riscos de política
                   ├─ 02 Cenas        narração, duração, descrição visual, prompt, IMAGE / VIDEO / IMAGE+MOTION
                   ├─ 03 Visuais      imagem por IA → movimento local (ffmpeg) ou vídeo por IA
                   ├─ 04 Narração     TTS por cena (duração real medida) + narração completa
                   ├─ 05 Thumbnail    conceitos, prompts, imagens 1280×720 e variações
                   ├─ 06 Metadados    títulos, descrição com capítulos reais, tags, palavras-chave
                   └─ 07 Exportação   ZIP para edição + timeline.json (base da montagem automática)
```

---

## Sumário

1. [Funcionalidades](#funcionalidades)
2. [Qualidade, tokens e custos](#qualidade-tokens-e-custos)
3. [Arquitetura](#arquitetura)
4. [Deploy: GitHub → GHCR → Portainer](#deploy-github--ghcr--portainer)
5. [Variáveis de ambiente](#variáveis-de-ambiente)
6. [Desenvolvimento local](#desenvolvimento-local)
7. [Testes](#testes)
8. [Próximos passos já previstos na arquitetura](#próximos-passos-já-previstos-na-arquitetura)
9. [Segurança](#segurança)
10. [Solução de problemas](#solução-de-problemas)

---

## Funcionalidades

### Canais e Skill
- Cada canal tem **idioma de produção** (pl-PL, de-DE, en-US, pt-BR…), país, público, nicho, estilo
  narrativo, tom, duração alvo, palavras por minuto, segundos por cena, estilo visual, estilo de
  thumbnail, **voz** (modelo, voz, velocidade, estilo de leitura) e nível de qualidade padrão.
- **Testar voz**: gera uma frase de exemplo no idioma do canal e mostra o custo real.
- **Skill**: manual do canal em Markdown, editável, com **histórico de versões, comparação (diff) e
  restauração**. Pode ser escrita pela IA a partir das configurações do canal.
- **Evolução da Skill**: o sistema registra suas decisões (prompts editados, troca de tipo de asset,
  instruções de reescrita, título escolhido, thumbnail favorita, descrição reescrita). Ao exportar um
  projeto, a IA propõe **aprendizados** com base nessas evidências; você aprova, rejeita ou edita.
  Aprendizados aprovados entram imediatamente em todas as chamadas de IA do canal e podem ser
  **consolidados** numa nova versão da Skill.

### Pipeline do projeto
| Etapa | O que acontece |
|---|---|
| **Roteiro** | Métricas medidas pelo sistema (palavras, duração estimada pelo WPM do idioma, frases repetidas, trechos de 5 palavras repetidos, frases longas) + análise da IA: notas (gancho, estrutura, coerência, retenção, originalidade, adequação ao canal), problemas com trecho e correção, **riscos de política do YouTube** (copyright, conteúdo reutilizado/inautêntico, spam/enganoso, desinformação, violência, conteúdo sintético que exige divulgação, pouco amigável a anunciantes…) e melhorias priorizadas. |
| **Cenas** | O roteiro é dividido em frases localmente (sem perder nem inventar texto) e a IA agrupa as frases em cenas, escreve a descrição visual (pt-BR), o prompt (inglês, **fiel ao que a narração diz**: as pessoas, objetos e lugares citados, fotorrealista com detalhes de época — a não ser que o estilo do canal peça ilustração) e decide **IMAGE / IMAGE + MOTION / VIDEO** com justificativa. Também escolhe a **transição** de entrada, um **efeito sonoro** (poucas cenas) e um **texto na tela** curto (datas, lugares, nomes, números — só quando combina). Você pode editar tudo, trocar o tipo e **reescrever só uma cena** com uma instrução. |
| **Visuais** | Imagem 1920×1080 por IA → **movimento de câmera local com ffmpeg** (zoom/pan suave, sem custo) ou **vídeo por IA** usando a imagem como primeiro quadro (quando o modelo aceita). Versões anteriores ficam guardadas para escolher. |
| **Narração** | TTS **por cena** (regenera só o trecho alterado), duração real medida com ffprobe; o clipe de movimento é re-renderizado para bater com o áudio. Narração completa em um MP3. |
| **Vídeo final** | **Monta sozinho** quando a narração (ou os visuais) termina e todas as cenas estão prontas — **sem IA e sem custo**, com ffmpeg no servidor: cenas na ordem e no tempo da narração, **transições** entre as cenas (dissolver, fade preto, flash, deslizar, zoom, desfoque, círculo), **texto com efeito de máquina de escrever** (com som de teclas), **efeitos sonoros sintetizados no servidor** (whoosh, impacto, subida, tensão, batimento, vento, estrondo, relógio — sem direitos autorais de terceiros), fade de abertura e encerramento. Cenas longas (> 12 s) ganham um segundo enquadramento no meio; vídeo IA mais curto que a narração continua com movimento suave do último quadro. MP4 H.264/AAC pronto para **baixar** na tela "Vídeo final" (também dá para montar de novo depois de editar). |
| **Thumbnail** | Conceitos (ideia, emoção, composição, texto curto no idioma do canal), prompts e imagens 1280×720 com variações; marque a favorita. |
| **Metadados** | 8 títulos com contagem de caracteres, descrição, **capítulos com os tempos reais do áudio**, tags (≤ 500 caracteres), hashtags e palavras-chave. |
| **Exportação** | ZIP organizado (abaixo) e aprendizados automáticos para a Skill. |
| **Piloto automático** | Um botão no projeto passa sozinho por todas as etapas que faltam (análise → cenas → narração → visuais → vídeo final → título/descrição → thumbnail → ZIP), gerando só o que ainda não existe. Pausa se algo falhar (ex.: saldo) ou se a análise apontar alto risco de política; você corrige e clica em Retomar. |
| **Arquivos** | Quanto o projeto ocupa no disco (também na lista de projetos e no painel) e quanto ocupa **cada parte**: cenas, imagens, clipes de movimento, vídeos IA, narração, vídeo final, thumbnails, pacotes ZIP, versões antigas e arquivos soltos. Cada parte pode ser **excluída** (análise e metadados também), com aviso do que precisa ser refeito e se isso custa. O roteiro nunca é apagado ali. |

```
projeto/
├── LEIA-ME.txt            como montar no CapCut
├── timeline.json          trilhas de vídeo, narração, legendas, música e efeitos (montagem futura)
├── projeto.json           dados completos + custos
├── 01_roteiro/            roteiro.txt · analise.md · analise.json
├── 02_cenas/              cenas.csv · cenas.json (início, duração, narração, prompts)
├── 03_visuais/            cena_001.mp4|jpg … na ordem da timeline  · imagens/ (1920×1080)
├── 04_narracao/           cena_001.mp3 … narracao_completa.mp3
├── 05_legendas/           legendas.srt sincronizadas
├── 06_thumbnail/          thumb_01_v1_ESCOLHIDA.jpg …  conceitos.json
└── 07_metadados/          titulo · titulos_alternativos · descricao · tags · capitulos
```

### Fila de geração
Tudo que é pesado roda **em segundo plano** no worker, com progresso ao vivo. Lotes ("gerar todas as
imagens") viram um job-grupo com filhos; se algo falhar, **“Repetir” refaz só o que falhou** — sem
regerar (nem pagar de novo) o que já deu certo. Erros temporários (429/5xx) são repetidos
automaticamente; saldo insuficiente (402) ou bloqueio de moderação param com a mensagem clara.

---

## Qualidade, tokens e custos

### Níveis
| | ECONOMY | BALANCED (padrão) | PREMIUM |
|---|---|---|---|
| Texto | família Gemini Flash | família Claude Sonnet | família Claude Opus |
| Imagens | o mais barato do catálogo · 1K | Gemini Flash Image (versão mais barata) · 1K | Gemini Pro Image · 2K |
| Cena mínima | 12 s (menos imagens) | 9 s | a do canal |
| Thumbnails | 2 conceitos × 1 | 3 × 2 (Flash Image) | 4 × 2 (Pro Image) |
| Vídeo IA | não usa | até ~3% das cenas · 720p | até ~10% das cenas · 1080p |

Os modelos **não são fixos no código**: o sistema lê o **catálogo real da OpenRouter**. Para texto e
narração vale a versão mais nova da família preferida; para imagem, thumbnail e vídeo, fora do
Premium, vale a opção **mais barata com preço real** (no Economy, a mais barata do catálogo inteiro).
Se a família não existir, escolhe pela faixa de preço. Em **Configurações** você fixa qualquer modelo
por nível e operação (a lista mostra o preço e pode ser ordenada do mais barato), resolução, duração
mínima por cena, % de vídeo, quantidade de thumbnails e esforço de raciocínio.

**Onde está o custo:** em um vídeo de ~19 min, quase todo o valor vem das **imagens** (uma por cena)
e do **vídeo IA**. Texto e narração custam centavos. Para baixar o total: aumente os *segundos por
cena* do canal (12–15 s), deixe o vídeo IA em 0% e escolha um modelo de imagem barato.

### Teto por vídeo (em reais)
Cada nível tem um **teto por vídeo** (padrão: Economy sem teto, Balanced **R$ 20**, Premium
**R$ 50**; 0 = sem teto). Se o plano padrão passar do teto, o sistema ajusta o plano daquele vídeo,
escolhendo a combinação de **melhor qualidade que cabe**. Ele pode, do que menos aparece para o que
mais aparece: reduzir/cortar o vídeo IA (inclusive cenas de vídeo já planejadas — as travadas
ficam), reduzir as thumbnails, usar o modelo de texto do nível abaixo, alongar as cenas até 12 s
(menos imagens), usar o modelo de imagem do nível abaixo e, por último, a voz do nível abaixo e
cenas de até 20 s. Modelos fixados por você (em Configurações ou a voz do canal) não são trocados;
imagens e voz já geradas num projeto mantêm o mesmo modelo. A estimativa mostra o total em R$ e
US$, o teto (✓/✕) e o que foi ajustado.

O plano escolhido é o que a produção usa: a divisão em cenas segue a duração planejada (e junta
cenas se a IA criar cenas demais) e todas as imagens do projeto usam o mesmo modelo. O teto vale
para o plano; refazer cenas gasta além dele (para um limite rígido use *Limite por projeto*).

A OpenRouter cobra em dólar; a conversão usa a **cotação do dia** (AwesomeAPI, com Frankfurter de
reserva, cache de 12 h). Sem acesso à internet, vale a última cotação obtida ou `USD_BRL`
(padrão 5,50). Em Configurações dá para fixar uma cotação.

### Estimativa antes de gerar (os três níveis lado a lado)
Cada linha mostra a origem do número:

| Marca | Origem |
|---|---|
| ● | preço publicado no catálogo da OpenRouter (`/models`, `/images/models/.../endpoints`, `/videos/models`) |
| ◆ | média dos **seus custos reais** já cobrados para o mesmo modelo (calibra a estimativa com o uso) |
| ≈ | preço real, mas quantidade aproximada (ex.: tokens por imagem/áudio em modelos cobrados por token) |
| ○ | local, sem custo (movimento ffmpeg, exportação) |
| — | o modelo não publica preço por unidade → o custo real aparece após a primeira geração |

Nada é inventado: sem dado suficiente, a linha mostra “—” em vez de um valor fictício.

### Custo real depois de gerar
Cada chamada é registrada num livro-caixa com tokens de entrada/saída, raciocínio e **custo real**:
`usage.cost` devolvido pela OpenRouter (texto, imagem e vídeo) ou consultado em `/generation`
(narração TTS, que devolve apenas o áudio). Você vê o consumo **por etapa, por projeto, por canal,
por modelo, por dia e total**.

### Saldo da OpenRouter
- Com `OPENROUTER_MANAGEMENT_KEY` (chave de gerenciamento): saldo da conta via `/credits`.
- Só com a chave normal: limite restante da chave (`/key`), se a chave tiver limite definido.
  **Dica:** crie a chave de API com um limite de gasto na OpenRouter — o painel mostra o restante.

### Limites de gasto
Em **Configurações → Limites de gasto** defina um teto **diário** e **por projeto**. Ao atingir,
novas gerações pagas param com aviso (renderização local e exportação continuam).

---

## Arquitetura

```
 Navegador (React)
      │  cookie HttpOnly · /api
      ▼
 API (FastAPI) ───────────────▶ PostgreSQL ◀──────────────── Worker(s)
  · login, canais, projetos       · dados                      · reserva jobs (SKIP LOCKED)
  · estimativas, custos           · fila de jobs                · vagas por tipo: llm, image,
  · serve o frontend              · livro-caixa de custos         tts, video, cpu (ffmpeg)
                                                                       │
                                        Providers (trocáveis) ◀────────┘
                                        ├─ OpenRouter: LLM · imagem · TTS · vídeo
                                        └─ Local: ffmpeg (movimento, áudio, ZIP)
                                                                       │
                                        Storage (/data) ◀──────────────┘  imagens · vídeos · áudios · exports
```

- **Uma imagem, vários papéis**: `api` (padrão), `worker`, `all` (API + worker no mesmo processo,
  para instalações mínimas) e `migrate`.
- **Fila no PostgreSQL**: sem Redis. Jobs com tentativas, backoff, cancelamento, grupos e
  recuperação de jobs travados (worker reiniciado). Pode rodar mais de um worker.
- **Providers separados por modalidade** (`backend/app/providers/`): `LLMProvider`,
  `ImageProvider`, `TTSProvider`, `VideoProvider`. Referências de modelo aceitam prefixo de provider
  (`openrouter:google/...`), então adicionar outro fornecedor = implementar a interface e registrar
  em `providers/registry.py`.
- **Migrações** com Alembic, aplicadas automaticamente ao iniciar a API; no PostgreSQL o banco é
  criado se não existir.

```
backend/
  app/
    api/            rotas REST
    jobs/           fila (queue.py), contexto e worker
    pipeline/       etapas: script, scenes, visuals, narration, thumbnail, metadata, learning, export,
                    estimate · prompts · schemas (JSON estruturado) · text (frases, SRT)
    providers/      openrouter.py · local.py (ffmpeg) · registry.py
    catalog.py      catálogo/preços da OpenRouter em cache
    tiers.py        níveis e escolha de modelos   ·  pricing.py  preços e estimativas
    usage.py        livro-caixa, agregações e limites de gasto
  alembic/          migrações
  tests/            pytest + simulador da OpenRouter (fake_openrouter.py)
frontend/           React 19 + Vite + Tailwind 4 (interface)
deploy/             stacks do Portainer (Swarm + Traefik e Docker standalone)
```

---

## Deploy: GitHub → GHCR → Portainer

```
git push (default) → GitHub Actions: testes + e2e → build multi-arquitetura → ghcr.io/dhqdev/dark-model:latest → Portainer
```

### 1. Imagem no GitHub Container Registry
O workflow `.github/workflows/ci.yml` roda a cada push na branch `default` (a branch padrão):
1. testes do backend em SQLite **e** PostgreSQL, build do frontend;
2. e2e: sobe o sistema contra um simulador da OpenRouter, executa o **pipeline completo** pela API e
   navega por todas as telas (computador e celular);
3. publica `ghcr.io/dhqdev/dark-model:latest` e `:sha-xxxxxxx` para **linux/amd64 e linux/arm64**
   (tags `v1.2.3` publicam também `:1.2.3` e `:1.2`).

Não é preciso configurar segredo para publicar (usa o `GITHUB_TOKEN`). O pacote nasce privado:
torne-o público em *GitHub → Packages → dark-model → Package settings* ou cadastre o registry no
Portainer (passo abaixo).

### 2. Portainer com Docker Swarm + Traefik (Oracle Cloud ARM64) — `dark.tekvosoft.com`
Arquivo: [`deploy/portainer-swarm-traefik.yml`](deploy/portainer-swarm-traefik.yml) — segue o mesmo
padrão das stacks existentes (rede `network_public`, entrypoint `websecure`, certresolver
`letsencryptresolver`) e **reaproveita o PostgreSQL da VPS** (`postgres_postgres`, o mesmo do n8n),
economizando memória na instância gratuita.

1. **DNS**: registro `A` de `dark.tekvosoft.com` apontando para o IP público da VPS.
2. **Registry** (se o pacote for privado): *Portainer → Registries → Add registry → Custom*:
   URL `ghcr.io`, usuário do GitHub e um token (classic) com escopo `read:packages`.
3. *Portainer → Stacks → Add stack → Web editor*: cole o arquivo e, em **Environment variables**,
   defina:

   | Variável | Valor |
   |---|---|
   | `APP_USERNAME` / `APP_PASSWORD` | seu login no estúdio |
   | `OPENROUTER_API_KEY` | `sk-or-v1-...` (de preferência com limite de gasto definido na OpenRouter) |
   | `APP_SECRET_KEY` | `openssl rand -base64 48` — guarde |
   | `POSTGRES_PASSWORD` | senha do usuário `postgres` do Postgres existente |
   | `OPENROUTER_MANAGEMENT_KEY` | opcional, para mostrar o saldo da conta |

4. **Deploy the stack**. Na primeira subida a API cria o banco `darkmodel` e aplica as migrações.
   Acesse `https://dark.tekvosoft.com`.

Na Ampere A1 (4 OCPUs) o worker roda até 2 renderizações ffmpeg em paralelo (`WORKER_LANES … cpu=2`);
as chamadas de IA rodam em paralelo nas outras vagas. Como referência, um clipe de movimento 1080p
de 7 s levou ~5 s para renderizar num servidor x86 de teste; para acelerar, use `MOTION_FPS=25` ou
`MOTION_SIZE=1280x720`.

> Prefere um PostgreSQL só do Dark Model? Use o modelo standalone abaixo como referência e adicione
> um serviço `postgres:17-alpine` na stack.

### 3. Portainer com Docker standalone (ou `docker compose`)
- Portainer: [`deploy/portainer-stack.yml`](deploy/portainer-stack.yml) — inclui PostgreSQL,
  API (porta `8000`) e worker. Defina as mesmas variáveis + `POSTGRES_PASSWORD`.
- Sem Portainer:
  ```bash
  cp .env.example .env    # preencha
  docker compose up -d --build
  ```

### 4. Atualização automática
- Manual: na stack, **Pull and redeploy** (Swarm: *Update the stack* com “re-pull image”).
- Automática: crie um **webhook** no serviço/stack do Portainer e cadastre a URL como secret
  `PORTAINER_WEBHOOK_URL` no repositório do GitHub; o workflow chama o webhook depois do build.

### Backup
- Volume `dark_model_data` (imagens, vídeos, áudios e ZIPs).
- Banco `darkmodel` no PostgreSQL (`pg_dump -U postgres darkmodel`).

---

## Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `APP_USERNAME`, `APP_PASSWORD` | sim | Login único. Trocar a senha encerra as sessões abertas. |
| `OPENROUTER_API_KEY` | sim | Chave da OpenRouter (fica só no servidor). |
| `APP_SECRET_KEY` | recomendada | Assina o cookie de sessão. Se vazia, é gerada e salva em `/data/secret.key`. |
| `OPENROUTER_MANAGEMENT_KEY` | não | Chave de gerenciamento, para ler o saldo da conta (`/credits`). |
| `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | * | Conexão PostgreSQL (a senha pode ter qualquer caractere). |
| `DATABASE_URL` | * | Alternativa: `postgresql://usuario:senha@host:5432/banco`. Sem nenhum dos dois, usa SQLite em `/data`. |
| `APP_PUBLIC_URL` | não | URL pública (identificação do app na OpenRouter). |
| `COOKIE_SECURE` | não | `true` quando o acesso é por HTTPS (Traefik). Com `http://IP:porta`, `false`. |
| `WORKER_LANES` | não | Vagas simultâneas por tipo: `llm=2,image=4,tts=3,video=2,cpu=1`. |
| `MOTION_SIZE`, `MOTION_FPS` | não | Resolução e fps dos clipes de movimento e do vídeo final (padrão `1920x1080`, `30`). |
| `OVERLAY_FONT` | não | Fonte (.ttf) do texto na tela do vídeo final. Padrão: DejaVu Sans Mono (já na imagem). |
| `USD_BRL`, `FX_AUTO` | não | Cotação usada sem acesso à cotação do dia (padrão `5.5`); `FX_AUTO=false` usa sempre `USD_BRL`. |
| `CATALOG_TTL_MINUTES` | não | Validade do cache do catálogo/preços (padrão 360). |
| `EMBEDDED_WORKER` | não | `true` roda o worker dentro da API (o papel `all` já faz isso). |
| `LOG_LEVEL`, `TZ` | não | Log e fuso horário. |

---

## Desenvolvimento local

Requisitos: Python 3.12, Node 22, ffmpeg.

```bash
# backend
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp ../.env.example .env            # APP_USERNAME, APP_PASSWORD, OPENROUTER_API_KEY…
.venv/bin/python -m app all        # API + worker em http://localhost:8000 (SQLite em backend/data)

# frontend (outro terminal) — proxy de /api para a porta 8000
cd frontend && npm install && npm run dev   # http://localhost:5173
```

**Sem gastar nada**: rode o simulador da OpenRouter e aponte o backend para ele.

```bash
cd backend
.venv/bin/python -m tests.fake_openrouter --port 9911 &
OPENROUTER_BASE_URL=http://127.0.0.1:9911/api/v1 OPENROUTER_API_KEY=fake .venv/bin/python -m app all
.venv/bin/python scripts/seed_demo.py --password <APP_PASSWORD>   # cria canal + projeto completo de exemplo
```

O simulador reproduz os formatos de resposta da API oficial (incluindo `usage.cost`,
`X-Generation-Id`, `/generation`, `/videos` com polling e `/credits` exigindo chave de gerenciamento);
as imagens, áudios e vídeos são placeholders.

---

## Testes

```bash
cd backend && .venv/bin/python -m pytest -q                       # SQLite
TEST_DATABASE_URL=postgresql://user:pass@localhost/db .venv/bin/python -m pytest -q   # PostgreSQL
cd frontend && npm run build                                       # tipos + build
npm run test:e2e   # com o sistema rodando (E2E_BASE_URL, E2E_PASSWORD, E2E_CHROME_PATH opcional)
```

Os testes cobrem autenticação (rate limit, CSRF, troca de senha), divisão de frases em vários
idiomas, preços e SKUs de vídeo, o **pipeline completo** de ponta a ponta (custos do livro-caixa
batendo com o que a API “cobrou”), retry só do que falhou, erros 402/429/5xx, limite de gasto,
cancelamento, recuperação de jobs travados e consistência das migrações com os modelos.

---

## Próximos passos já previstos na arquitetura

| Evolução | Onde encaixa |
|---|---|
| **Legendas queimadas / estilos** | `pipeline/text.py` já gera o SRT sincronizado com o áudio real; `montage.py` já desenha texto (drawtext). |
| **Música de fundo** | `montage.py` já mixa narração + efeitos; basta uma trilha de música (biblioteca própria) com ducking. |
| **Publicação no YouTube** | metadados finais, thumbnail escolhida e capítulos já estão no projeto; nova etapa com OAuth. |
| **Analytics e aprendizado por desempenho** | `FeedbackEvent` + aprendizados da Skill: basta registrar métricas do YouTube como novos sinais. |
| **Outros providers** (ElevenLabs, fal.ai, modelos locais) | implementar a interface em `providers/` e registrar em `providers/registry.py`. |

---

## Segurança

- As chaves de API existem **só no servidor** (variáveis da Stack); a interface recebe apenas
  “configurada: sim/não”.
- Sessão em cookie **HttpOnly + SameSite=Lax** (e `Secure` com HTTPS), assinada; trocar
  `APP_PASSWORD` invalida todas as sessões.
- Proteção contra CSRF (cabeçalho obrigatório em requisições que alteram dados), limite de
  tentativas de login, Content-Security-Policy, `X-Frame-Options: DENY`.
- Arquivos gerados só são servidos para quem está logado. O container roda como usuário sem
  privilégios.
- Não coloque segredos no repositório nem no arquivo da stack: use as variáveis do Portainer.

---

## Solução de problemas

| Sintoma | Causa / solução |
|---|---|
| Login não “gruda” | Acesso por `http://IP:porta` com `COOKIE_SECURE=true`. Use HTTPS ou `COOKIE_SECURE=false`. |
| “Nenhum worker online” | O serviço `worker` não está rodando (ou use o papel `all`). Veja os logs do serviço. |
| Saldo aparece “—” | A OpenRouter só informa o saldo da conta com chave de gerenciamento; ou defina um limite na chave. |
| “Modelo não encontrado” | *Configurações → Atualizar catálogo* e escolha outro modelo para o nível. |
| “Saldo insuficiente na OpenRouter” | Recarregue créditos e use **Repetir** na fila (refaz só o que falhou). |
| Tarefa “parada” após reiniciar | Jobs sem sinal de vida por 5 min voltam para a fila automaticamente. |
