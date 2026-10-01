"""Instruções enviadas aos modelos. Saídas para o usuário em pt-BR; conteúdo do vídeo no idioma do canal."""

from __future__ import annotations

from . import text

ORIGINALITY = """\
ORIGINALITY & PLATFORM SAFETY (always):
- The channel must publish original work that adds real value (YouTube "reused" and "inauthentic/mass-produced" content policies).
- Never reproduce copyrighted text, lyrics, or long quotes; never imitate a specific creator's script.
- Visuals: no logos, trademarks, copyrighted characters, watermarks, or readable text unless explicitly asked.
- Never depict real private individuals. For real public/historical figures, describe them generically (role, era, clothing) instead of a photorealistic likeness.
- Avoid gore, sexualized content and anything harmful to minors."""

# Fidelidade e realismo das imagens: cada imagem mostra o que a narração está dizendo naquele momento.
FIDELITY = """\
IMAGE FIDELITY (most important):
- Show LITERALLY what the narration says at that moment: the specific people, objects, places, vehicles, animals and actions it mentions — not a vague mood or a symbol.
- Start the prompt with the main subject and action in plain words (who/what, doing what, where, when), then the setting details, then shot, light and palette.
- When the narration mentions or implies people (workers, soldiers, a crowd, a family, an engineer…), SHOW them: realistic faces and hands, period-accurate clothing and tools, natural poses, believable scale.
- Be concrete and accurate: era, region, architecture, technology of the time, landscape type, weather, time of day (e.g. "1860s steam locomotive with a balloon smokestack", not "an old train").
- Prefer real-looking documentary photography (photorealistic, natural light, real textures, depth of field) over abstract, symbolic or fantasy imagery — unless the channel visual style asks for illustration.
- One clear focal subject per image; avoid collages, split screens and impossible compositions."""

_ILLUSTRATED = ("illustrat", "anime", "cartoon", "painting", "watercolor", "watercolour", "3d render", "pixel", "comic",
                "sketch", "drawing", "desenho", "ilustra", "pintura", "aquarela", "animação", "animacao", "vector")


def wants_realism(visual_style: str) -> bool:
    low = (visual_style or "").lower()
    return not any(k in low for k in _ILLUSTRATED)


REVIEWER_LANGUAGE = "Write every explanation/assessment field in Brazilian Portuguese (pt-BR). Quote excerpts in the script's original language."


def script_analysis(context: str, script: str, metrics: dict, channel_language: str) -> tuple[str, str]:
    system = (
        "You are a senior YouTube script editor and policy reviewer for faceless (no on-camera host) "
        "documentary-style channels. You give precise, actionable, honest feedback and you flag platform risks "
        "early. Respond with JSON only.\n\n" + ORIGINALITY
    )
    reps = "; ".join(f'"{r["text"][:80]}" ×{r["count"]}' for r in metrics.get("repeated_sentences", [])) or "none"
    phrases = "; ".join(f'"{r["text"]}" ×{r["count"]}' for r in metrics.get("repeated_phrases", [])) or "none"
    user = f"""{context}

## MEASURED FACTS (computed by software — trust these numbers)
- Words: {metrics['words']} | sentences: {metrics['sentences']} | paragraphs: {metrics['paragraphs']}
- Estimated narration: {metrics['estimated_minutes']} min at {metrics['words_per_minute']} wpm (target {metrics['target_min']}–{metrics['target_max']} min)
- Long sentences (>40 words): {metrics['long_sentences']}
- Repeated sentences: {reps}
- Repeated 5-word phrases: {phrases}

## TASK
Review the script below, written in {channel_language}.
1. Scores 0–10: hook (first ~30 s), structure, coherence, retention potential, originality, channel_fit (versus the channel settings and Skill).
2. summary, hook_assessment, structure (main sections in order: title, the words each one starts with, assessment), ending_assessment, pacing_assessment (consider the measured duration vs target).
3. issues: concrete problems (structure, coherence, repetition, pacing, clarity, factual doubts, length, style, hook, ending) with severity, exact excerpt and a fix.
4. repetition_notes: redundancy worth cutting (use the measured repetitions).
5. policy_risks: ONLY real risks with an exact excerpt. Categories: copyright, reused_content, inauthentic_content (templated/mass-produced feel), spam_deceptive (claims or promises not delivered), misinformation (health, elections, conspiracies stated as fact), violence_graphic, hate_harassment, sexual_content, dangerous_activities, medical_financial_claims, child_safety, privacy (private individuals), synthetic_disclosure (realistic depiction of real people/events that would require YouTube's altered/synthetic content disclosure), advertiser_unfriendly (profanity, tragedies, shocking topics → limited ads), other. Empty list if none.
6. originality_assessment and channel_fit_assessment.
7. improvements: up to 8 prioritized, actionable improvements.
8. verdict: "high_risk" if any high-severity policy risk; "approved" if no high-severity issue or risk; otherwise "needs_revision".
{REVIEWER_LANGUAGE}

## SCRIPT
{script}"""
    return system, user


def scene_plan(
    context: str,
    sentences: list[text.Segment],
    *,
    first: int,
    last: int,
    scene_seconds: float,
    wpm: int,
    video_percent: int,
    visual_style: str,
    previous: str,
    block: int,
    blocks: int,
    language: str = "the narration language",
) -> tuple[str, str]:
    words_per_scene = max(6, round(scene_seconds * wpm / 60))
    system = (
        "You are the director, editor and visual planner of faceless YouTube documentaries. You split narration into "
        "scenes and design one strong, faithful visual per scene that keeps retention high, plus the edit "
        "(transition, sound effect, on-screen text). Respond with JSON only.\n\n" + FIDELITY + "\n\n" + ORIGINALITY
    )
    numbered = "\n".join(f"[{s.index}] {s.text}" for s in sentences)
    video_rule = (
        f"VIDEO is expensive: use it for at most ~{video_percent}% of the scenes, only for high-impact moments with real motion "
        "(action, transformation, natural phenomena, dramatic reveals)."
        if video_percent > 0 else "Do NOT use VIDEO in this quality tier."
    )
    user = f"""{context}

## TASK (block {block} of {blocks})
The narration below is split into numbered sentences. Group CONSECUTIVE sentences into scenes.
- Every sentence from [{first}] to [{last}] must belong to exactly one scene, in order, with no gaps or overlaps. "start" and "end" are inclusive sentence numbers.
- Target ≈ {scene_seconds:g} s per scene (≈ {words_per_scene} words at {wpm} wpm). Cut when the subject, place, time or idea changes; a long sentence can be a scene alone.
- visual_description: what the viewer sees, 1–2 sentences in Brazilian Portuguese (pt-BR), for the editor.
- prompt: detailed ENGLISH prompt for an image model following IMAGE FIDELITY — main subject and action first, then setting and era details, composition/shot type, camera angle, lighting, mood, color palette. Keep the channel visual style: "{visual_style or 'photorealistic cinematic documentary'}". No text, letters, captions, logos or watermarks.
- Vary the shots (establishing wide, medium, close-up detail, aerial, macro, silhouette, over-the-shoulder) and never repeat the same composition in consecutive scenes.
- asset_type: IMAGE_MOTION (default — still image animated with slow camera motion), IMAGE (static: maps, diagrams, very short beats under ~3 s), VIDEO (AI video clip). {video_rule}
- asset_type_reason: short justification in pt-BR.
- motion: camera move for IMAGE_MOTION — zoom_in (tension, focus), zoom_out (reveal context), pan_left/pan_right (landscapes, wide scenes), pan_up/pan_down (tall subjects), static (IMAGE).
- transition: how THIS scene enters after the previous one — dissolve (default, most scenes), fadeblack (time jump, new chapter, somber moment), flash (shock, explosion, sudden reveal), slide (travel, movement, "meanwhile"), zoom (diving into a detail), blur (memory, flashback, dream), circle (reveal of a place or object), cut (fast tense sequences). Vary, but keep it tasteful: mostly dissolve.
- sfx: optional sound effect at the start of the scene, ONLY when it adds impact — whoosh (fast movement, transition of place), impact (dramatic reveal, collision, decisive moment), riser (build-up right before a reveal), tension (suspense, danger), heartbeat (fear, critical moment), wind (open landscapes, desert, storm), rumble (heavy machinery, trains, earthquakes, explosions far away), clock (deadline, waiting, time pressure). Use "none" for most scenes (at most ~1 in 5 scenes has a sound effect).
- overlay_text: short on-screen text in {language} ONLY when it helps the viewer — a date, a place, a name, a number/statistic or a striking short quote (max 6 words / 45 characters, no emojis). It appears with a typewriter effect. Leave it EMPTY for most scenes (at most ~1 in 6 scenes); always use it for the first mention of a key date or place.

Previous scene, for visual continuity: {previous or '(start of the video)'}

## SENTENCES
{numbered}"""
    return system, user


def scene_rewrite(context: str, scene: dict, prev_desc: str, next_desc: str, instruction: str,
                  video_percent: int, visual_style: str) -> tuple[str, str]:
    system = ("You are the director of a faceless YouTube documentary. You redesign the visual of ONE scene. "
              "Respond with JSON only.\n\n" + FIDELITY + "\n\n" + ORIGINALITY)
    video_rule = (f"VIDEO is expensive (≈{video_percent}% of scenes at most); use it only for strong motion moments."
                  if video_percent > 0 else "Do NOT choose VIDEO in this quality tier.")
    user = f"""{context}

## SCENE TO REDESIGN
Narration: {scene['narration']}
Current visual description: {scene['visual_description']}
Current prompt: {scene['prompt']}
Current asset type: {scene['asset_type']}
Previous scene: {prev_desc or '—'}
Next scene: {next_desc or '—'}

## OWNER INSTRUCTION
{instruction or 'Propose a better, more striking and original visual that fits the narration.'}

## RULES
- visual_description in pt-BR (1–2 sentences); prompt in ENGLISH following IMAGE FIDELITY (main subject and action first, then setting, shot, angle, light, mood, palette), visual style "{visual_style or 'photorealistic cinematic documentary'}", no text/logos/watermarks.
- asset_type IMAGE_MOTION (default), IMAGE (static) or VIDEO. {video_rule} asset_type_reason in pt-BR.
- motion: zoom_in, zoom_out, pan_left, pan_right, pan_up, pan_down or static."""
    return system, user


def image_prompt(prompt: str, visual_style: str) -> str:
    style = f" Visual style: {visual_style.strip()}." if visual_style.strip() else ""
    realism = (" Photorealistic documentary photograph, realistic people and objects, accurate period details, "
               "natural lighting, real textures, sharp focus on the main subject." if wants_realism(visual_style) else "")
    return (f"{prompt.strip()}{style}{realism} Widescreen 16:9 cinematic frame. Original image. "
            "No text, no letters, no captions, no logos, no watermark.")


def video_prompt(prompt: str, motion: str, visual_style: str) -> str:
    moves = {
        "zoom_in": "slow push-in camera movement", "zoom_out": "slow pull-back camera movement",
        "pan_left": "slow lateral pan to the left", "pan_right": "slow lateral pan to the right",
        "pan_up": "slow upward tilt", "pan_down": "slow downward tilt", "static": "locked-off camera",
    }
    style = f" Visual style: {visual_style.strip()}." if visual_style.strip() else ""
    return (f"{prompt.strip()} Camera: {moves.get(motion, 'subtle cinematic camera movement')}, natural motion, "
            f"realistic physics.{style} No text, no logos, no watermark.")


def thumbnail_concepts(context: str, summary: str, titles: list[str], count: int, language: str,
                       text_mode: str, thumbnail_style: str) -> tuple[str, str]:
    system = ("You are a YouTube packaging strategist for faceless channels. You design thumbnails with high CTR "
              "that honestly represent the video (no misleading bait). Respond with JSON only.\n\n" + ORIGINALITY)
    text_rule = (
        f'overlay_text: max 4 words in {language}, punchy. The prompt MUST ask the image model to render exactly that text '
        'in huge bold sans-serif letters with strong contrast (write the text in double quotes inside the prompt).'
        if text_mode == "in_image" else
        f"overlay_text: max 4 words in {language} (the editor will add it later). The prompt must ask for NO text in the image "
        "and leave clean negative space for the text."
    )
    titles_txt = "\n".join(f"- {t}" for t in titles) or "- (not defined yet)"
    user = f"""{context}

## VIDEO
Summary: {summary}
Title candidates:
{titles_txt}

## TASK
Create {count} DISTINCT thumbnail concepts (different angles: curiosity gap, emotion, contrast/before-after, mystery, scale).
- name, idea, emotion, composition, rationale: in Brazilian Portuguese (pt-BR).
- {text_rule}
- prompt: ENGLISH prompt for a 16:9 thumbnail — one bold focal subject, high contrast, dramatic lighting, readable at small size, uncluttered background, rule of thirds. Thumbnail style: "{thumbnail_style or 'bold, cinematic, high contrast'}".
- The thumbnail must reflect the real content of the video."""
    return system, user


def thumbnail_image_prompt(prompt: str, overlay: str, text_mode: str, thumbnail_style: str) -> str:
    style = f" Style: {thumbnail_style.strip()}." if thumbnail_style.strip() else ""
    if text_mode == "in_image" and overlay.strip() and overlay.strip() not in prompt:
        prompt = f'{prompt.strip()} Render the text "{overlay.strip()}" in huge bold sans-serif letters, perfectly spelled.'
    elif text_mode != "in_image":
        prompt = f"{prompt.strip()} No text or letters in the image; leave clean negative space for a title."
    return f"{prompt.strip()}{style} YouTube thumbnail, 16:9, high contrast, sharp focus, original artwork, no logos, no watermark."


def metadata(context: str, script: str, outline: str, language: str, overlay: str) -> tuple[str, str]:
    system = ("You are a YouTube SEO and packaging specialist for faceless documentary channels. Titles create "
              "curiosity without misleading. Respond with JSON only.\n\n" + ORIGINALITY)
    user = f"""{context}

## SCENE OUTLINE (scene number · start time · first words)
{outline}

## THUMBNAIL TEXT
{overlay or '—'}

## TASK — everything for the viewer in {language}
- titles: 8 options, ideally ≤ 70 characters (never > 100), keyword near the start, curiosity without false promises; "angle" = short label in pt-BR (ex.: "curiosidade", "número", "pergunta").
- description: 2 opening lines with the hook and main keyword, then 2–4 short paragraphs and a soft call to subscribe. Do NOT include chapters or hashtags (they are added automatically). Max 4500 characters.
- chapters: 5–12 chapters; "scene" = number of the scene where it starts (the first chapter must be scene 1); titles ≤ 40 characters.
- tags: 15–30 tags (broad + specific, no "#"), total under 450 characters.
- hashtags: exactly 3, starting with "#".
- primary_keywords (3–5) and secondary_keywords (5–10).
- policy_notes: in pt-BR, any risk of misleading metadata or sensitive topic (empty list if none).

## SCRIPT
{script}"""
    return system, user


def learnings(skill: str, accepted: list[str], project_summary: str, feedback: str) -> tuple[str, str]:
    system = ("You maintain the production playbook (Skill) of a YouTube channel. You turn the owner's decisions "
              "into short, reusable rules. Respond with JSON only.")
    accepted_txt = "\n".join(f"- {a}" for a in accepted) or "- (none)"
    user = f"""## CURRENT SKILL
{skill or '(empty)'}

## ALREADY APPROVED LEARNINGS
{accepted_txt}

## FINISHED PROJECT
{project_summary}

## OWNER DECISIONS AND EDITS (evidence)
{feedback or '(no explicit edits recorded)'}

## TASK
Propose up to 8 NEW learnings that will make future videos of this channel more consistent with what the owner approved.
- Each learning: a concrete, reusable rule in Brazilian Portuguese (pt-BR) starting with a verb ("Preferir…", "Evitar…", "Usar…").
- Only when supported by the evidence above; rationale (pt-BR) must cite the evidence.
- Do not repeat anything already in the Skill or approved learnings. Return an empty list if there is nothing new.
- category: script, scenes, visuals, narration, thumbnail, metadata or general."""
    return system, user


def skill_draft(channel_block: str, language: str) -> tuple[str, str]:
    system = ("You write production playbooks (Skills) for faceless YouTube channels. The Skill guides an AI "
              "production pipeline. Respond with JSON only.")
    user = f"""## CHANNEL
{channel_block}

## TASK
Write the channel Skill in Brazilian Portuguese (pt-BR), in Markdown, practical and specific to this niche and audience.
Sections: 1) Identidade e público; 2) Roteiro (gancho nos primeiros 30 s, estrutura, ritmo, retenção, CTA); 3) Narração (tom, ritmo, vocabulário — lembrando que o vídeo é produzido em {language}); 4) Direção visual (estilo, enquadramentos, paleta, continuidade, o que evitar); 5) Cenas (duração média, quando usar IMAGE, IMAGE_MOTION e VIDEO); 6) Thumbnails; 7) Títulos, descrição e tags; 8) Originalidade e políticas do YouTube; 9) Checklist final.
Return "content" (the Markdown) and "summary" (one sentence in pt-BR)."""
    return system, user


def skill_consolidate(skill: str, accepted: list[str]) -> tuple[str, str]:
    system = ("You maintain the production playbook (Skill) of a YouTube channel. You integrate approved learnings "
              "into the right sections, keeping it concise and free of contradictions. Respond with JSON only.")
    learned = "\n".join(f"- {a}" for a in accepted)
    user = f"""## CURRENT SKILL
{skill or '(empty)'}

## APPROVED LEARNINGS TO INTEGRATE
{learned}

## TASK
Rewrite the Skill in Brazilian Portuguese (pt-BR), in Markdown, integrating every learning in the appropriate section.
When a learning contradicts the current text, the learning wins. Keep everything else that is still valid. Be concise.
Return "content" (full new Skill) and "summary" (what changed, one or two sentences in pt-BR)."""
    return system, user
