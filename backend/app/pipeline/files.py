"""Arquivos do projeto: quanto cada parte do processo ocupa no disco e exclusão por parte.

Cada parte diz o que acontece depois de excluir (o que precisa ser refeito e se isso custa).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..jobs import queue
from ..models import Asset, AssetKind, Job, Project
from ..storage import get_storage, project_dir


@dataclass(frozen=True)
class Part:
    key: str
    label: str
    stage: str  # aba do projeto
    regen: str  # free | paid | manual (o que custa refazer)
    note: str  # o que acontece ao excluir
    kinds: tuple[str, ...] = ()
    jobs: tuple[str, ...] = ()  # tarefas que impedem a exclusão enquanto rodam


PARTS: tuple[Part, ...] = (
    Part("analysis", "Análise do roteiro", "roteiro", "paid",
         "Apaga notas, problemas e riscos apontados pela IA. O roteiro continua.", jobs=("script.analyze",)),
    Part("scenes", "Cenas", "cenas", "paid",
         "Apaga todas as cenas e TUDO que depende delas: imagens, clipes, vídeos IA e narração.",
         kinds=(AssetKind.IMAGE.value, AssetKind.MOTION.value, AssetKind.VIDEO.value, AssetKind.AUDIO.value),
         jobs=("scenes.plan", "scene.rewrite", "visual.image", "visual.motion", "visual.video", "narration.scene")),
    Part("images", "Imagens das cenas", "visuais", "paid",
         "As cenas continuam; as imagens precisam ser geradas de novo (custa) para montar o vídeo.",
         kinds=(AssetKind.IMAGE.value,), jobs=("visual.image", "visual.motion", "visual.video")),
    Part("motion", "Clipes de movimento", "visuais", "free",
         "Refeitos de graça no servidor a partir das imagens (ou na montagem do vídeo).",
         kinds=(AssetKind.MOTION.value,), jobs=("visual.motion",)),
    Part("videos", "Vídeos IA das cenas", "visuais", "paid",
         "As cenas de vídeo IA ficam sem clipe; gerar de novo custa. Na montagem viram imagem com movimento.",
         kinds=(AssetKind.VIDEO.value,), jobs=("visual.video",)),
    Part("narration", "Narração", "narracao", "paid",
         "Apaga o áudio de todas as cenas e a narração completa; narrar de novo custa.",
         kinds=(AssetKind.AUDIO.value, AssetKind.NARRATION.value), jobs=("narration.scene", "narration.merge")),
    Part("final", "Vídeo final", "video", "free",
         "Pode ser montado de novo de graça (se imagens e narração continuarem).",
         kinds=(AssetKind.FINAL.value,), jobs=("render.final",)),
    Part("thumbnails", "Thumbnails", "thumbnail", "paid",
         "Apaga os conceitos e as imagens de thumbnail.",
         kinds=(AssetKind.THUMBNAIL.value,), jobs=("thumbnail.concepts", "thumbnail.image")),
    Part("metadata", "Título, descrição e tags", "metadados", "paid",
         "Apaga as sugestões da IA e o título, a descrição e as tags escolhidos.", jobs=("metadata.generate",)),
    Part("exports", "Pacotes ZIP (CapCut)", "exportacao", "free",
         "Podem ser gerados de novo de graça.", kinds=(AssetKind.EXPORT.value,), jobs=("export.zip",)),
    Part("old_versions", "Versões antigas", "visuais", "manual",
         "Imagens, clipes e áudios de versões anteriores que não estão em uso, narrações completas e pacotes "
         "antigos. O que está em uso continua."),
    Part("orphans", "Arquivos soltos", "custos", "free",
         "Arquivos no disco que nenhuma parte do projeto usa mais (sobras de tarefas canceladas)."),
)
PART_BY_KEY = {p.key: p for p in PARTS}


class FilesError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------ medição


def project_sizes(db: Session, project_ids: list[int]) -> dict[int, int]:
    """Bytes por projeto (soma dos arquivos registrados) — rápido para listas."""
    if not project_ids:
        return {}
    rows = db.execute(select(Asset.project_id, func.coalesce(func.sum(Asset.size_bytes), 0))
                      .where(Asset.project_id.in_(project_ids)).group_by(Asset.project_id)).all()
    return {pid: int(n) for pid, n in rows}


def _in_use(db: Session, project: Project) -> set[int]:
    keep: set[int] = set()
    for s in project.scenes:
        keep.update(x for x in (s.image_asset_id, s.clip_asset_id, s.audio_asset_id) if x)
    for kind in (AssetKind.NARRATION.value, AssetKind.EXPORT.value, AssetKind.FINAL.value):
        latest = db.scalar(select(func.max(Asset.id)).where(Asset.project_id == project.id, Asset.kind == kind))
        if latest:
            keep.add(latest)
    return keep


def _old_versions(db: Session, project: Project) -> list[Asset]:
    keep = _in_use(db, project)
    kinds = (AssetKind.IMAGE.value, AssetKind.MOTION.value, AssetKind.VIDEO.value, AssetKind.AUDIO.value,
             AssetKind.NARRATION.value, AssetKind.EXPORT.value, AssetKind.FINAL.value)
    return [a for a in db.scalars(select(Asset).where(Asset.project_id == project.id, Asset.kind.in_(kinds)))
            if a.id not in keep]


def _disk_files(project_id: int) -> dict[str, int]:
    storage = get_storage()
    root = storage.path(project_dir(project_id))
    out: dict[str, int] = {}
    if not root.exists():
        return out
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            p = os.path.join(dirpath, name)
            try:
                out[os.path.relpath(p, storage.root)] = os.path.getsize(p)
            except OSError:
                pass
    return out


def _orphans(db: Session, project: Project) -> dict[str, int]:
    known = set(db.scalars(select(Asset.path).where(Asset.project_id == project.id)))
    return {rel: size for rel, size in _disk_files(project.id).items() if rel not in known}


def storage_report(db: Session, project: Project) -> dict[str, Any]:
    by_kind = {k: (int(n), int(b)) for k, n, b in db.execute(
        select(Asset.kind, func.count(Asset.id), func.coalesce(func.sum(Asset.size_bytes), 0))
        .where(Asset.project_id == project.id).group_by(Asset.kind)).all()}
    old = _old_versions(db, project)
    orphans = _orphans(db, project)
    disk = sum(_disk_files(project.id).values())
    parts = []
    for p in PARTS:
        if p.key == "old_versions":
            count, size = len(old), sum(a.size_bytes or 0 for a in old)
        elif p.key == "orphans":
            count, size = len(orphans), sum(orphans.values())
        elif p.key == "analysis":
            count, size = int(bool(project.analysis)), 0
        elif p.key == "metadata":
            count, size = int(bool(project.metadata_suggestions or project.selected_title or project.description)), 0
        elif p.key == "scenes":
            n = len(project.scenes)
            count, size = n, sum(by_kind.get(k, (0, 0))[1] for k in p.kinds)
        elif p.key == "thumbnails":
            count = len(project.concepts)
            size = by_kind.get(AssetKind.THUMBNAIL.value, (0, 0))[1]
        else:
            count = sum(by_kind.get(k, (0, 0))[0] for k in p.kinds)
            size = sum(by_kind.get(k, (0, 0))[1] for k in p.kinds)
        parts.append({"key": p.key, "label": p.label, "stage": p.stage, "regen": p.regen, "note": p.note,
                      "count": count, "bytes": size, "busy": _busy(db, project, p)})
    total = sum(b for _, b in by_kind.values())
    return {"total_bytes": total, "disk_bytes": disk, "parts": parts}


def _busy(db: Session, project: Project, part: Part) -> bool:
    if not part.jobs:
        return False
    return db.scalar(select(Job.id).where(Job.project_id == project.id, Job.kind.in_(part.jobs),
                                          Job.status.in_(queue.ACTIVE)).limit(1)) is not None


# ------------------------------------------------------------------ exclusão


def _drop_assets(db: Session, project: Project, assets: list[Asset]) -> int:
    storage = get_storage()
    ids = {a.id for a in assets}
    freed = 0
    for s in project.scenes:
        if s.image_asset_id in ids:
            s.image_asset_id = None
        if s.clip_asset_id in ids:
            s.clip_asset_id = None
        if s.audio_asset_id in ids:
            s.audio_asset_id = None
            s.audio_duration = None
    for c in project.concepts:
        if c.selected_asset_id in ids:
            c.selected_asset_id = None
    for a in assets:
        freed += a.size_bytes or 0
        storage.delete(a.path)
        db.delete(a)
    return freed


def _assets(db: Session, project: Project, kinds: tuple[str, ...]) -> list[Asset]:
    return list(db.scalars(select(Asset).where(Asset.project_id == project.id, Asset.kind.in_(kinds))))


def delete_part(db: Session, project: Project, key: str) -> dict[str, Any]:
    part = PART_BY_KEY.get(key)
    if part is None:
        raise FilesError("Parte do projeto desconhecida.", 404)
    if _busy(db, project, part):
        raise FilesError(f"Há tarefas de '{part.label}' rodando neste projeto. Aguarde ou cancele na fila.", 409)
    freed = 0
    if key == "analysis":
        project.analysis = None
        project.analysis_at = None
        project.analysis_script_hash = ""
    elif key == "metadata":
        project.metadata_suggestions = None
        project.selected_title = ""
        project.description = ""
        project.tags = []
    elif key == "scenes":
        freed = _drop_assets(db, project, _assets(db, project, part.kinds))
        db.flush()
        for s in list(project.scenes):
            db.delete(s)
        project.scenes_planned_at = None
        project.scenes_script_hash = ""
    elif key == "thumbnails":
        freed = _drop_assets(db, project, _assets(db, project, part.kinds))
        db.flush()
        for c in list(project.concepts):
            db.delete(c)
    elif key == "old_versions":
        freed = _drop_assets(db, project, _old_versions(db, project))
    elif key == "orphans":
        storage = get_storage()
        for rel, size in _orphans(db, project).items():
            storage.delete(rel)
            freed += size
    else:
        freed = _drop_assets(db, project, _assets(db, project, part.kinds))
    db.flush()
    _prune_empty_dirs(project.id)
    return {"part": key, "label": part.label, "freed_bytes": freed}


def _prune_empty_dirs(project_id: int) -> None:
    root = get_storage().path(project_dir(project_id))
    if not root.exists():
        return
    for dirpath, _dirs, _files in sorted(os.walk(root), key=lambda x: -len(x[0])):
        try:
            if dirpath != str(root) and not os.listdir(dirpath):
                os.rmdir(dirpath)
        except OSError:
            pass

