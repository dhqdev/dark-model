from __future__ import annotations

import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..deps import get_db, get_or_404, require_user
from ..models import Asset, AssetKind, Scene, ThumbnailConcept
from ..storage import get_storage

router = APIRouter(prefix="/assets", tags=["assets"], dependencies=[Depends(require_user)])


def _filename(a: Asset) -> str:
    name = a.path.rsplit("/", 1)[-1]
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name) or f"asset-{a.id}"


@router.get("/{asset_id}/file")
def asset_file(asset_id: int, download: bool = False, db: Session = Depends(get_db)) -> FileResponse:
    a = get_or_404(db, Asset, asset_id, "Arquivo")
    storage = get_storage()
    if not storage.exists(a.path):
        raise HTTPException(404, "Arquivo não está mais no armazenamento.")
    headers = {"Cache-Control": "private, max-age=86400"}
    return FileResponse(storage.path(a.path), media_type=a.mime, headers=headers,
                        filename=_filename(a) if download or a.kind == AssetKind.EXPORT.value else None)


@router.delete("/{asset_id}")
def delete_asset(asset_id: int, db: Session = Depends(get_db)) -> dict:
    a = get_or_404(db, Asset, asset_id, "Arquivo")
    if a.scene_id:
        s = db.get(Scene, a.scene_id)
        if s is not None:
            for field in ("image_asset_id", "clip_asset_id", "audio_asset_id"):
                if getattr(s, field) == a.id:
                    setattr(s, field, None)
                    if field == "audio_asset_id":
                        s.audio_duration = None
    if a.concept_id:
        c = db.get(ThumbnailConcept, a.concept_id)
        if c is not None and c.selected_asset_id == a.id:
            c.selected_asset_id = None
    get_storage().delete(a.path)
    db.delete(a)
    db.commit()
    return {"ok": True}
