from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import serialize
from ..deps import get_db, get_or_404, require_user
from ..jobs import queue
from ..models import Asset, FeedbackEvent, ThumbnailConcept
from ..pipeline.common import delete_asset_files

router = APIRouter(prefix="/thumbnails", tags=["thumbnails"], dependencies=[Depends(require_user)])


class ConceptPatch(BaseModel):
    name: str | None = None
    overlay_text: str | None = Field(None, max_length=120)
    prompt: str | None = None


class SelectIn(BaseModel):
    asset_id: int


class MoreIn(BaseModel):
    variations: int = Field(1, ge=1, le=4)


def _concept(db: Session, concept_id: int) -> ThumbnailConcept:
    return get_or_404(db, ThumbnailConcept, concept_id, "Conceito")


def _out(db: Session, c: ThumbnailConcept) -> dict:
    assets = {a.id: a for a in db.scalars(select(Asset).where(Asset.concept_id == c.id))}
    return serialize.concept(c, assets)


@router.patch("/{concept_id}")
def update_concept(concept_id: int, body: ConceptPatch, db: Session = Depends(get_db)) -> dict:
    c = _concept(db, concept_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(c, k, v)
    db.commit()
    return _out(db, c)


@router.post("/{concept_id}/generate")
def generate_more(concept_id: int, body: MoreIn, db: Session = Depends(get_db)) -> dict:
    c = _concept(db, concept_id)
    p = c.project
    jobs = [queue.enqueue(db, "thumbnail.image", label=f"Thumbnail '{c.name[:40]}' (variação)", project_id=p.id,
                          channel_id=p.channel_id, target_id=c.id, dedupe=False) for _ in range(body.variations)]
    db.commit()
    return {"jobs": [serialize.job(j) for j in jobs]}


@router.post("/{concept_id}/select")
def select_image(concept_id: int, body: SelectIn, db: Session = Depends(get_db)) -> dict:
    c = _concept(db, concept_id)
    a = get_or_404(db, Asset, body.asset_id, "Imagem")
    if a.concept_id != c.id:
        raise HTTPException(400, "A imagem não pertence a este conceito.")
    c.selected_asset_id = a.id
    db.add(FeedbackEvent(channel_id=c.project.channel_id, project_id=c.project_id, kind="thumbnail_selected",
                         data={"name": c.name, "idea": c.idea, "overlay_text": c.overlay_text, "asset_id": a.id}))
    db.commit()
    return _out(db, c)


@router.delete("/{concept_id}")
def delete_concept(concept_id: int, db: Session = Depends(get_db)) -> dict:
    c = _concept(db, concept_id)
    delete_asset_files(db, list(db.scalars(select(Asset).where(Asset.concept_id == c.id))))
    db.delete(c)
    db.commit()
    return {"ok": True}
