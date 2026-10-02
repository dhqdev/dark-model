# Histórico e decisões

Registro curto do que já foi feito e por quê. Acrescente uma linha a cada mudança relevante.

## 2026-10-01 — primeira versão e ajustes

- **Base:** estúdio completo (canais + Skill, pipeline roteiro → exportação, fila no Postgres,
  livro-caixa de custos, OpenRouter como gateway único, Docker multi-arquitetura + Portainer).
- **CI** passou a disparar na branch `default` (a branch padrão do repositório não é `main`).
- **Custo menor por padrão:** imagens do modelo mais barato com preço real fora do Premium e cenas
  mais longas (mínimo 12 s Economy / 9 s Balanced) — a imagem é o maior custo de um vídeo.
- **Teto por vídeo em R$ por nível** (Balanced R$ 20, Premium R$ 50) com planejador que corta primeiro
  o que menos aparece; respostas da IA mais tolerantes (`schemas.Lenient`).
- **Gemini TTS:** só devolve PCM → pedir `pcm` e converter para MP3 (24 kHz).
- **Vídeo final automático** (ffmpeg, sem custo) com transição, efeito sonoro e texto na tela por cena
  (migração 0003); o teto passou a valer para todas as etapas (plano gravado em `Project.plan`).
- **Aba Arquivos:** tamanho em disco por parte e exclusão por parte.
- **ffmpeg 7** (imagem Docker): `fps=` depois de `setpts` para o `xfade`, pedaços em MP4, sem
  `filter_complex_script`; CI ganhou o job `ffmpeg-image` com o ffmpeg do Debian.
- **Montagem com progresso real** (`-progress`), tempo restante e `keepalive` (não ser tomada como
  travada e reenfileirada).
- **Título/descrição:** aceitar campos com outros nomes (`ALIASES`) e não remover o campo `title` do
  JSON Schema enviado à IA (`llm.strict_schema`).

## 2026-10-02

- **Documentação para o Claude:** `CLAUDE.md` + `docs/`.
- **Piloto automático** por projeto (migração 0004): passa sozinho por todas as etapas, só gera o que
  falta, pausa em falha/alto risco, anti-loop de gasto.
- **Auditoria de sincronia:** sem atraso acumulado (testado com áudios de durações quebradas: vídeo e
  áudio terminam juntos e cada troca de imagem acontece no início da fala). Ajuste: transições centradas
  no corte da fala (antes a imagem nova só aparecia inteira 0,4–0,9 s depois da frase começar).
- **Auditoria dos planos:** todas as etapas usam o modelo do plano, mas a divisão em cenas aceitava
  qualquer quantidade de vídeo IA que coubesse no teto (ex.: 20% num nível de 3%). Agora fica no máximo
  a % do plano. Reescrever cena passou a usar a % do plano, não a padrão do nível.
- **Planejado × real** na aba Custos.

## Ideias já previstas (não feitas)

Legendas queimadas, música de fundo com ducking, publicação no YouTube (OAuth), métricas do YouTube
como sinal de aprendizado, outros providers (ElevenLabs, fal.ai, locais) — ver README.
