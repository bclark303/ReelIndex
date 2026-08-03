from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.inventory_records import (
    InventoryRecordBlocked,
    InventoryRecordNotFound,
    delete_movie_inventory_record,
)

router = APIRouter(tags=["movies"])


@router.delete("/movies/{movie_id}")
def delete_movie_record(movie_id: str, db: Session = Depends(get_db)):
    try:
        return delete_movie_inventory_record(db, movie_id)
    except InventoryRecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InventoryRecordBlocked as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
