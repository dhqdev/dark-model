"""Etapa 7 — pacote organizado para edição (CapCut etc.) + timeline.json para montagem automática futura."""

from __future__ import annotations

import csv
import io
import json
import re
import tempfile
import unicodedata
import zipfile
from pathlib import Path

from .. import __version__, media
from ..db import session_scope
from ..jobs.context import JobContext, handler
from ..models import Asset, AssetKind, AssetType, utcnow
from ..storage import get_storage
from .. import usage as usage_ledger
from . import text
from .common import StageError, load_project, new_asset_path, scene_timeline

TEXT_EXT = {".txt", ".json", ".csv", ".srt", ".md"}


def slugify(value: str, fallback: str = "projeto") -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value[:60] or fallback


def _analysis_md(analysis: dict) -> str:
    ai = analysis.get("ai") or {}
    m = analysis.get("metrics") or {}
    lines = [f"# Análise do roteiro", "", f"Veredito: **{ai.get('verdict', '—')}**", "",
             f"Palavras: {m.get('words')} · duração estimada: {m.get('estimated_minutes')} min "
             f"(alvo {m.get('target_min')}–{m.get('target_max')} min)", "", "## Resumo", ai.get("summary", ""), ""]
    if ai.get("scores"):
        lines += ["## Notas"] + [f"- {k}: {v}/10" for k, v in ai["scores"].items()] + [""]
    if ai.get("policy_risks"):
        lines += ["## Riscos de política"]
        lines += [f"- [{r['severity']}] {r['category']}: {r['explanation']} — \"{r['excerpt']}\" → {r['recommendation']}"
                  for r in ai["policy_risks"]] + [""]
    if ai.get("issues"):
        lines += ["## Problemas"]
        lines += [f"- [{i['severity']}] {i['type']}: {i['explanation']} — \"{i['excerpt']}\" → {i['suggestion']}"
                  for i in ai["issues"]] + [""]
    if ai.get("improvements"):
        lines += ["## Melhorias"] + [f"- {x}" for x in ai["improvements"]]
    return "\n".join(lines)


README = """DARK MODEL — PACOTE DE PRODUÇÃO
================================

Projeto: {title}
Canal:   {channel} ({language})
Gerado:  {date} (UTC) · Dark Model v{version}
Duração: {duration} ({timing})

ESTRUTURA
  01_roteiro/     roteiro final e análise da IA
  02_cenas/       lista de cenas (CSV/JSON) com narração, tempos e prompts
  03_visuais/     um arquivo por cena, na ordem (cena_001...). Vídeo (.mp4) quando a cena é
                  VIDEO ou IMAGEM+MOVIMENTO; imagem (.jpg) quando é IMAGEM estática.
                  imagens/ contém todas as imagens-base em 1920x1080.
  04_narracao/    um MP3 por cena + narracao_completa.mp3
  05_legendas/    legendas.srt sincronizadas com a narração
  06_thumbnail/   thumbnails geradas (escolhidas marcadas com *_ESCOLHIDA)
  07_metadados/   título, alternativas, descrição (com capítulos), tags
  timeline.json   linha do tempo completa (base para montagem automática)

COMO MONTAR NO CAPCUT
  1. Importe 04_narracao/narracao_completa.mp3 na trilha de áudio.
  2. Importe todos os arquivos de 03_visuais/ (já ordenados) e coloque-os em sequência.
     Use 02_cenas/cenas.csv para conferir início e duração de cada cena.
  3. Importe 05_legendas/legendas.srt (Texto → Legendas → Importar).
  4. Ajuste transições, música e efeitos.

{warnings}"""


@handler("export.zip")
def export_project(ctx: JobContext) -> dict:
    include_clips = bool(ctx.payload.get("include_clips", True))
    gap = float(ctx.payload.get("gap", 0.0))
    storage = get_storage()
    with session_scope() as db:
        project = load_project(db, ctx.project_id)
        channel = project.channel
        scenes = list(project.scenes)
        if not scenes and not project.script.strip():
            raise StageError("Nada para exportar: o projeto não tem roteiro nem cenas.")
        timeline = scene_timeline(scenes, gap)
        assets = {a.id: a for a in db.query(Asset).filter(Asset.project_id == project.id)}
        concepts = list(project.concepts)
        costs = usage_ledger.project_costs(db, project.id)
        data = {
            "title": project.title, "selected_title": project.selected_title, "description": project.description,
            "tags": project.tags, "quality": project.quality, "script": project.script,
            "analysis": project.analysis, "metadata": project.metadata_suggestions or {},
            "channel": {"name": channel.name, "language": channel.language, "country": channel.country,
                        "niche": channel.niche},
        }
        scene_rows = []
        for s, start, dur in timeline:
            scene_rows.append({
                "position": s.position, "start": round(start, 3), "duration": round(dur, 3),
                "audio_duration": s.audio_duration, "narration": s.narration, "asset_type": s.asset_type,
                "motion": s.motion, "visual_description": s.visual_description, "prompt": s.prompt,
                "image": assets.get(s.image_asset_id), "clip": assets.get(s.clip_asset_id),
                "audio": assets.get(s.audio_asset_id),
            })
        thumbs = []
        for c in concepts:
            files = [a for a in assets.values() if a.concept_id == c.id and a.kind == AssetKind.THUMBNAIL.value]
            thumbs.append({"concept": {"name": c.name, "idea": c.idea, "overlay_text": c.overlay_text,
                                       "prompt": c.prompt, "selected_asset_id": c.selected_asset_id},
                           "files": sorted(files, key=lambda a: a.id)})
    slug = slugify(project.selected_title or project.title)
    root = f"{slug}/"
    warnings: list[str] = []
    ctx.progress(0.05, "montando pacote", force=True)
    with tempfile.TemporaryDirectory(dir=storage.tmp_dir()) as tmp:
        zpath = Path(tmp) / "export.zip"
        with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as z:

            def put_text(name: str, content: str) -> None:
                z.writestr(root + name, content)

            def put_file(name: str, asset: Asset) -> bool:
                if asset is None or not storage.exists(asset.path):
                    return False
                compress = zipfile.ZIP_DEFLATED if Path(name).suffix in TEXT_EXT else zipfile.ZIP_STORED
                z.write(storage.path(asset.path), root + name, compress_type=compress)
                return True

            # 01 roteiro
            put_text("01_roteiro/roteiro.txt", data["script"] or "")
            if data["analysis"]:
                put_text("01_roteiro/analise.json", json.dumps(data["analysis"], ensure_ascii=False, indent=2))
                put_text("01_roteiro/analise.md", _analysis_md(data["analysis"]))
            # 02 cenas
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["cena", "inicio", "fim", "duracao_s", "tipo", "movimento", "narracao", "descricao_visual",
                        "prompt", "arquivo_visual", "arquivo_audio"])
            timeline_video, timeline_audio, srt_entries = [], [], []
            total = len(scene_rows)
            for i, row in enumerate(scene_rows, start=1):
                ctx.progress(0.05 + 0.75 * i / max(total, 1), f"empacotando cena {i}/{total}")
                n = f"{row['position']:03d}"
                visual_file = ""
                clip, image = row["clip"], row["image"]
                use_clip = (include_clips and clip is not None and row["asset_type"] != AssetType.IMAGE.value
                            and ((row["asset_type"] == AssetType.VIDEO.value and clip.kind == AssetKind.VIDEO.value)
                                 or (row["asset_type"] == AssetType.IMAGE_MOTION.value and clip.kind == AssetKind.MOTION.value)))
                if use_clip and put_file(f"03_visuais/cena_{n}.mp4", clip):
                    visual_file = f"03_visuais/cena_{n}.mp4"
                if image is not None:
                    if not visual_file and put_file(f"03_visuais/cena_{n}.jpg", image):
                        visual_file = f"03_visuais/cena_{n}.jpg"
                    else:
                        put_file(f"03_visuais/imagens/cena_{n}.jpg", image)
                if not visual_file:
                    warnings.append(f"cena {row['position']}: sem visual gerado")
                audio_file = ""
                if row["audio"] is not None and put_file(f"04_narracao/cena_{n}.mp3", row["audio"]):
                    audio_file = f"04_narracao/cena_{n}.mp3"
                else:
                    warnings.append(f"cena {row['position']}: sem narração gerada")
                end = row["start"] + row["duration"]
                w.writerow([row["position"], text.srt_timestamp(row["start"]), text.srt_timestamp(end),
                            f"{row['duration']:.2f}", row["asset_type"], row["motion"], row["narration"],
                            row["visual_description"], row["prompt"], visual_file, audio_file])
                timeline_video.append({"scene": row["position"], "start": row["start"], "duration": row["duration"],
                                       "type": row["asset_type"], "motion": row["motion"], "file": visual_file or None,
                                       "image": (f"03_visuais/imagens/cena_{n}.jpg" if visual_file.endswith(".mp4") and image else visual_file or None)})
                timeline_audio.append({"scene": row["position"], "start": row["start"], "duration": row["duration"],
                                       "file": audio_file or None})
                srt_entries.append((row["start"], row["duration"], row["narration"]))
            put_text("02_cenas/cenas.csv", buf.getvalue())
            put_text("02_cenas/cenas.json", json.dumps(
                [{k: v for k, v in r.items() if k not in ("image", "clip", "audio")} for r in scene_rows],
                ensure_ascii=False, indent=2))
            # narração completa
            audio_paths = [storage.path(r["audio"].path) for r in scene_rows if r["audio"] is not None]
            if scene_rows and len(audio_paths) == len(scene_rows):
                ctx.progress(0.85, "juntando narração completa", force=True)
                full = Path(tmp) / "narracao_completa.mp3"
                media.concat_audio(audio_paths, full, gap_seconds=gap)
                z.write(full, root + "04_narracao/narracao_completa.mp3", compress_type=zipfile.ZIP_STORED)
            elif scene_rows:
                warnings.append("narração completa não gerada: faltam áudios de cenas")
            # 05 legendas
            if srt_entries:
                put_text("05_legendas/legendas.srt", text.build_srt(srt_entries))
            # 06 thumbnails
            for ti, t in enumerate(thumbs, start=1):
                for vi, a in enumerate(t["files"], start=1):
                    chosen = "_ESCOLHIDA" if t["concept"]["selected_asset_id"] == a.id else ""
                    put_file(f"06_thumbnail/thumb_{ti:02d}_v{vi}{chosen}.jpg", a)
            if thumbs:
                put_text("06_thumbnail/conceitos.json", json.dumps([t["concept"] for t in thumbs], ensure_ascii=False,
                                                                   indent=2))
            # 07 metadados
            meta = data["metadata"]
            put_text("07_metadados/titulo.txt", data["selected_title"] or data["title"])
            if meta.get("titles"):
                put_text("07_metadados/titulos_alternativos.txt",
                         "\n".join(f"{t['title']}  [{t.get('angle', '')}]" for t in meta["titles"]))
            put_text("07_metadados/descricao.txt", data["description"] or meta.get("description", ""))
            put_text("07_metadados/tags.txt", ", ".join(data["tags"] or meta.get("tags", [])))
            if meta.get("chapters"):
                put_text("07_metadados/capitulos.txt", "\n".join(f"{c['time']} {c['title']}" for c in meta["chapters"]))
            put_text("07_metadados/metadados.json", json.dumps(meta, ensure_ascii=False, indent=2))
            total_duration = (timeline[-1][1] + timeline[-1][2]) if timeline else 0.0
            timing = ("tempos reais do áudio" if scenes and all(s.audio_duration for s in scenes)
                      else "tempos estimados — gere a narração para sincronizar")
            put_text("timeline.json", json.dumps({
                "version": 1, "width": 1920, "height": 1080, "fps": 30, "duration": round(total_duration, 3),
                "timing": "audio" if timing.startswith("tempos reais") else "estimate",
                "tracks": {"video": timeline_video, "narration": timeline_audio,
                           "subtitles": "05_legendas/legendas.srt" if srt_entries else None,
                           "music": [], "sfx": []},
            }, ensure_ascii=False, indent=2))
            put_text("projeto.json", json.dumps({
                "project": {k: v for k, v in data.items() if k != "analysis"}, "costs": costs,
                "exported_at": utcnow().isoformat() + "Z", "app_version": __version__,
            }, ensure_ascii=False, indent=2, default=str))
            put_text("LEIA-ME.txt", README.format(
                title=data["selected_title"] or data["title"], channel=data["channel"]["name"],
                language=data["channel"]["language"], date=utcnow().strftime("%Y-%m-%d %H:%M"), version=__version__,
                duration=text.timecode(total_duration), timing=timing,
                warnings=("AVISOS\n" + "\n".join(f"  - {w}" for w in warnings)) if warnings else "",
            ))
        ctx.progress(0.95, "salvando pacote", force=True)
        rel = new_asset_path(ctx.project_id, "exports", slug, "zip")
        size = storage.import_file(rel, zpath)
    with session_scope() as db:
        asset = Asset(project_id=ctx.project_id, kind=AssetKind.EXPORT.value, path=rel, mime="application/zip",
                      size_bytes=size, provider="local", model="export", params={"warnings": warnings,
                                                                                  "include_clips": include_clips},
                      job_id=ctx.job_id, duration=round(total_duration, 3))
        db.add(asset)
        db.flush()
        project = load_project(db, ctx.project_id)
        project.status = "exported"
        if project.channel.auto_learn:
            from ..jobs import queue

            queue.enqueue(db, "skill.learn", label=f"Aprendizados de '{project.title[:60]}'", project_id=project.id,
                          channel_id=project.channel_id)
        asset_id = asset.id
    return {"message": f"pacote pronto ({size / 1_048_576:.1f} MB)" + (f" · {len(warnings)} avisos" if warnings else ""),
            "asset_id": asset_id, "warnings": warnings}
