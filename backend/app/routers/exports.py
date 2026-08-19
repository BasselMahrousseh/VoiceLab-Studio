from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..models import ExportBatch
from ..schemas import ExportOut, ExportParams
from ..services.exporter import run_export
from ..services import storage
from ..services.database_backup import backup_sqlite

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


@router.post("/database-backup", response_model=dict)
def create_database_backup(settings: Settings = Depends(get_settings)):
    try:
        return backup_sqlite(settings)
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(409, str(exc))


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
    filename = batch.zip_rel_path.rsplit("/", 1)[-1]
    try:
        stream = storage.iter_export(settings, batch.zip_rel_path)
        first = next(stream)
    except Exception as exc:
        raise HTTPException(404, f"Zip file unavailable: {exc}")

    def body():
        yield first
        yield from stream

    return StreamingResponse(
        body(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
