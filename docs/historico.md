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

## Ideias já previstas (não feitas)

Legendas queimadas, música de fundo com ducking, publicação no YouTube (OAuth), métricas do YouTube
como sinal de aprendizado, outros providers (ElevenLabs, fal.ai, locais) — ver README.
