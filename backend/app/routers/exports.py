from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..models import ExportBatch
from ..schemas import ExportOut, ExportParams
from ..services.exporter import run_export

router = APIRouter(prefix="/exports", tags=["exports"])


@router.get("", response_model=list[ExportOut])
def list_exports(db: Session = Depends(get_db)):
    return db.query(ExportBatch).order_by(ExportBatch.id.desc()).all()


@router.post("", response_model=ExportOut)
def create_export(
    params: ExportParams,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    batch = run_export(db, params.model_dump(), settings)
    return batch


@router.get("/{batch_id}/download")
def download_export(
    batch_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    batch = db.get(ExportBatch, batch_id)
    if not batch:
        raise HTTPException(404, "Export not found")
    if not batch.zip_rel_path:
        raise HTTPException(404, "This export has no zip archive")
    path = settings.export_dir / batch.zip_rel_path
    if not path.exists():
        raise HTTPException(404, "Zip file missing on disk")
    return FileResponse(path, media_type="application/zip", filename=path.name)
