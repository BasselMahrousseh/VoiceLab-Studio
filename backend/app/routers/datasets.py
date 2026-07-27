import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..deps import require_admin
from ..models import LANGUAGES, Dataset, Recording, Script, User
from ..schemas import (
    AddScriptsIn,
    DatasetCreate,
    DatasetOut,
    DatasetPatch,
    ScriptImportIn,
    UserCreate,
    UserOut,
)
from .auth import create_user, user_out
from .scripts import _script_out, create_scripts_from_items

router = APIRouter(prefix="/datasets", tags=["datasets"], dependencies=[Depends(require_admin)])


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "dataset"


def _unique_slug(db: Session, name: str) -> str:
    base = _slugify(name)
    slug = base
    n = 2
    while db.query(Dataset).filter_by(slug=slug).first():
        slug = f"{base}-{n}"
        n += 1
    return slug


def dataset_out(db: Session, ds: Dataset) -> DatasetOut:
    out = DatasetOut.model_validate(ds)
    out.script_count = (
        db.query(func.count(Script.id)).filter(Script.dataset_id == ds.id).scalar()
    )
    accepted = (
        db.query(
            func.count(Recording.id),
            func.coalesce(func.sum(Recording.duration_sec), 0.0),
        )
        .join(Script, Recording.script_pk == Script.id)
        .filter(Script.dataset_id == ds.id, Recording.human_status == "accepted")
        .one()
    )
    out.accepted_count = accepted[0]
    out.accepted_duration_sec = round(accepted[1], 1)
    out.recorder_count = (
        db.query(func.count(User.id)).filter(User.dataset_id == ds.id).scalar()
    )
    return out


@router.get("", response_model=list[DatasetOut])
def list_datasets(db: Session = Depends(get_db)):
    rows = db.query(Dataset).order_by(Dataset.id.desc()).all()
    return [dataset_out(db, d) for d in rows]


@router.post("", response_model=DatasetOut)
def create_dataset(payload: DatasetCreate, db: Session = Depends(get_db)):
    languages = list(dict.fromkeys(payload.languages or [payload.language]))
    invalid = [language for language in languages if language not in LANGUAGES]
    if invalid:
        raise HTTPException(400, f"Unsupported dataset language tags: {', '.join(invalid)}")
    ds = Dataset(
        slug=_unique_slug(db, payload.name),
        name=payload.name.strip(),
        description=payload.description,
        instructions=payload.instructions,
        dialect=payload.dialect,
        language=languages[0],
        languages=languages,
        text_policy=payload.text_policy.strip(),
        target_sample_count=payload.target_sample_count,
        target_avg_duration_sec=payload.target_avg_duration_sec,
    )
    db.add(ds)
    db.commit()
    db.refresh(ds)
    return dataset_out(db, ds)


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: int, db: Session = Depends(get_db)):
    ds = db.get(Dataset, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    return dataset_out(db, ds)


@router.patch("/{dataset_id}", response_model=DatasetOut)
def patch_dataset(dataset_id: int, payload: DatasetPatch, db: Session = Depends(get_db)):
    ds = db.get(Dataset, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    data = payload.model_dump(exclude_unset=True)
    if "languages" in data:
        languages = list(dict.fromkeys(data["languages"] or []))
        if not languages:
            raise HTTPException(400, "Select at least one dataset language")
        invalid = [language for language in languages if language not in LANGUAGES]
        if invalid:
            raise HTTPException(400, f"Unsupported dataset language tags: {', '.join(invalid)}")
        existing_languages = {
            language
            for (language,) in db.query(Script.language)
            .filter(Script.dataset_id == dataset_id)
            .distinct()
            .all()
        }
        excluded = existing_languages - set(languages)
        if excluded:
            raise HTTPException(
                409,
                "Cannot remove language tags already used by scripts: "
                + ", ".join(sorted(excluded)),
            )
        data["languages"] = languages
        ds.language = languages[0]
    for key, value in data.items():
        setattr(ds, key, value)
    db.commit()
    db.refresh(ds)
    return dataset_out(db, ds)


@router.post("/{dataset_id}/scripts")
def add_scripts(
    dataset_id: int,
    payload: AddScriptsIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    ds = db.get(Dataset, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    items = _parse_lines(payload)
    if not items:
        raise HTTPException(400, "No script lines provided")
    imported, skipped = create_scripts_from_items(
        db,
        settings,
        items,
        source="import",
        dataset_id=dataset_id,
        allow_warnings=payload.allow_warnings,
        allowed_languages=set(ds.languages or [ds.language]),
    )
    return {"imported": len(imported), "skipped": skipped}


@router.post("/{dataset_id}/import")
def import_scripts_into_dataset(
    dataset_id: int,
    payload: ScriptImportIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Import structured script items (e.g. reviewed GenAI candidates) into a
    dataset, preserving their per-item style/domain/training_text."""
    ds = db.get(Dataset, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    imported, skipped = create_scripts_from_items(
        db,
        settings,
        [i.model_dump() for i in payload.items],
        source=payload.source,
        dataset_id=dataset_id,
        generation_batch=payload.generation_batch,
        generation_model=payload.generation_model,
        allow_warnings=payload.allow_warnings,
        allowed_languages=set(ds.languages or [ds.language]),
    )
    return {
        "imported": len(imported),
        "skipped": skipped,
        "items": [_script_out(db, s) for s in imported],
    }


def _parse_lines(payload: AddScriptsIn) -> list[dict]:
    import json

    items: list[dict] = []
    for raw in payload.text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("{"):
            try:
                obj = json.loads(line)
            except Exception:
                continue
            items.append(
                {
                    "style": payload.style,
                    "domain": payload.domain,
                    "dialect": payload.dialect,
                    "language": payload.language,
                    **obj,
                }
            )
        else:
            items.append(
                {
                    "display_text": line,
                    "style": payload.style,
                    "domain": payload.domain,
                    "dialect": payload.dialect,
                    "language": payload.language,
                }
            )
    return items


@router.get("/{dataset_id}/recorders", response_model=list[UserOut])
def dataset_recorders(dataset_id: int, db: Session = Depends(get_db)):
    users = (
        db.query(User)
        .filter(User.dataset_id == dataset_id, User.role == "recorder")
        .order_by(User.id)
        .all()
    )
    return [user_out(db, u) for u in users]


@router.post("/{dataset_id}/recorders", response_model=UserOut)
def add_recorder(
    dataset_id: int,
    payload: UserCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Create a recorder account pre-assigned to this dataset."""
    ds = db.get(Dataset, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    payload.role = "recorder"
    payload.dataset_id = dataset_id
    return create_user(payload, db=db, _=admin)
