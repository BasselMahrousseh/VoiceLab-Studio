import json
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..deps import require_admin
from ..models import Recording, Script
from ..schemas import (
    FlagIn,
    GenerateParams,
    ScriptImportIn,
    ScriptOut,
    ScriptPatch,
)
from ..services import llm_scripts
from ..services import text_normalize as tn
from ..services import text_policy

router = APIRouter(prefix="/scripts", tags=["scripts"])


def _generation_params(params: GenerateParams, db: Session) -> dict:
    data = params.model_dump()
    additions = data.get("policy_text", "").strip()
    policy = text_policy.get_policy(db)
    if additions:
        policy += "\n\n## Dataset-specific additions\n\n" + additions
    data["policy_text"] = policy
    return data


def _script_out(db: Session, s: Script) -> ScriptOut:
    out = ScriptOut.model_validate(s)
    out.take_count = (
        db.query(func.count(Recording.id)).filter(Recording.script_pk == s.id).scalar()
    )
    return out


def create_scripts_from_items(
    db: Session,
    settings: Settings,
    items: list[dict],
    *,
    source: str = "import",
    dataset_id: int | None = None,
    generation_batch: str | None = None,
    generation_model: str | None = None,
    allow_warnings: bool = True,
    allowed_languages: set[str] | None = None,
) -> tuple[list[Script], list[dict]]:
    """Validate and persist a batch of script items. Shared by the /scripts
    import endpoint and dataset creation. Returns (imported, skipped)."""
    existing_hashes = {h for (h,) in db.query(Script.normalized_hash).all()}
    existing_texts = [tn.normalize_arabic(t) for (t,) in db.query(Script.training_text).all()]
    batch_hashes: set[str] = set()

    imported: list[Script] = []
    skipped: list[dict] = []
    for item in items:
        v = llm_scripts.validate_item(item, existing_hashes, existing_texts, batch_hashes)
        if allowed_languages and v["computed"]["language"] not in allowed_languages:
            v["ok"] = False
            v["errors"].append(
                f"language '{v['computed']['language']}' is not enabled for this dataset"
            )
        if not v["ok"] or (v["warnings"] and not allow_warnings):
            skipped.append(
                {
                    "display_text": item.get("display_text", ""),
                    "errors": v["errors"],
                    "warnings": v["warnings"],
                }
            )
            continue
        c = v["computed"]
        script = Script(
            script_id="PENDING",
            dataset_id=dataset_id,
            display_text=c["display_text"],
            training_text=c["training_text"],
            msa_equivalent=c["msa_equivalent"],
            language=c["language"],
            dialect=c["dialect"],
            style=c["style"],
            domain=c["domain"],
            tags=c["tags"],
            length_bucket=c["length_bucket"],
            word_count=c["word_count"],
            char_count=c["char_count"],
            source=source,
            generation_batch=generation_batch,
            generation_model=generation_model,
            notes=item.get("notes", "") or c["note"],
            priority=item.get("priority", 100),
            normalized_hash=tn.normalized_hash(c["training_text"]),
        )
        db.add(script)
        db.flush()  # assign primary key
        script.script_id = f"{settings.script_id_prefix}_{c['style'].upper()}_{script.id:06d}"
        existing_hashes.add(script.normalized_hash)
        imported.append(script)
    db.commit()
    return imported, skipped


@router.get("", response_model=dict)
def list_scripts(
    status: str | None = None,
    style: str | None = None,
    domain: str | None = None,
    dialect: str | None = None,
    language: str | None = None,
    dataset_id: int | None = None,
    search: str | None = None,
    active: bool | None = None,
    limit: int = Query(default=50, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(Script)
    if status:
        q = q.filter(Script.status == status)
    if style:
        q = q.filter(Script.style == style)
    if domain:
        q = q.filter(Script.domain == domain)
    if dialect:
        q = q.filter(Script.dialect == dialect)
    if language:
        q = q.filter(Script.language == language)
    if dataset_id is not None:
        q = q.filter(Script.dataset_id == dataset_id)
    if active is not None:
        q = q.filter(Script.active == active)
    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                Script.display_text.like(like),
                Script.training_text.like(like),
                Script.script_id.like(like),
            )
        )
    total = q.count()
    items = q.order_by(Script.id.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [_script_out(db, s) for s in items]}


@router.get("/stats")
def script_stats(db: Session = Depends(get_db)):
    def group(col):
        return {k: v for k, v in db.query(col, func.count(Script.id)).group_by(col).all()}

    accepted = (
        db.query(
            func.count(Recording.id),
            func.coalesce(func.sum(Recording.duration_sec), 0.0),
        )
        .filter(Recording.human_status == "accepted")
        .one()
    )
    return {
        "total": db.query(func.count(Script.id)).scalar(),
        "by_status": group(Script.status),
        "by_style": group(Script.style),
        "by_domain": group(Script.domain),
        "by_dialect": group(Script.dialect),
        "by_language": group(Script.language),
        "by_length": group(Script.length_bucket),
        "accepted_recordings": accepted[0],
        "accepted_duration_sec": round(accepted[1], 1),
    }


@router.get("/next", response_model=ScriptOut | None)
def next_script(
    exclude_id: int | None = None,
    style: str | None = None,
    domain: str | None = None,
    dataset_id: int | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(Script).filter(
        Script.active.is_(True), Script.status.in_(["new", "recorded"])
    )
    if exclude_id:
        q = q.filter(Script.id != exclude_id)
    if style:
        q = q.filter(Script.style == style)
    if domain:
        q = q.filter(Script.domain == domain)
    if dataset_id is not None:
        q = q.filter(Script.dataset_id == dataset_id)
    # 'new' scripts first (cover unrecorded content), then re-record leftovers
    s = (
        q.filter(Script.status == "new").order_by(Script.priority, Script.id).first()
        or q.order_by(Script.priority, Script.id).first()
    )
    return _script_out(db, s) if s else None


@router.get("/queue-count")
def queue_count(dataset_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(func.count(Script.id)).filter(
        Script.active.is_(True), Script.status.in_(["new", "recorded"])
    )
    if dataset_id is not None:
        q = q.filter(Script.dataset_id == dataset_id)
    remaining = q.scalar()
    return {"remaining": remaining}


@router.post("/import")
def import_scripts(
    payload: ScriptImportIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: object = Depends(require_admin),
):
    imported, skipped = create_scripts_from_items(
        db,
        settings,
        [i.model_dump() for i in payload.items],
        source=payload.source,
        generation_batch=payload.generation_batch,
        generation_model=payload.generation_model,
        allow_warnings=payload.allow_warnings,
    )
    return {
        "imported": len(imported),
        "skipped": skipped,
        "items": [_script_out(db, s) for s in imported],
    }


@router.post("/generate")
def generate(
    params: GenerateParams,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: object = Depends(require_admin),
):
    """Generate candidate scripts via the configured LLM. Returns candidates
    with validation flags for human preview — nothing is saved here."""
    if not settings.llm_configured():
        raise HTTPException(
            503,
            "LLM endpoint is not configured. Set AZURE_OPENAI_ENDPOINT, "
            "AZURE_OPENAI_API_KEY and LLM_DEPLOYMENT in .env",
        )
    try:
        items = llm_scripts.generate_scripts(_generation_params(params, db), settings)
    except Exception as exc:
        raise HTTPException(502, f"LLM generation failed: {type(exc).__name__}: {exc}")

    existing_hashes = {h for (h,) in db.query(Script.normalized_hash).all()}
    existing_texts = [
        tn.normalize_arabic(t) for (t,) in db.query(Script.training_text).all()
    ]
    batch_hashes: set[str] = set()
    results = [
        llm_scripts.validate_item(item, existing_hashes, existing_texts, batch_hashes)
        for item in items
    ]
    return {
        "model": settings.llm_deployment,
        "batch_name": params.batch_name,
        "count": len(results),
        "candidates": results,
    }


@router.post("/generate/stream")
def generate_stream(
    params: GenerateParams,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: object = Depends(require_admin),
):
    """Stream candidate scripts as newline-delimited JSON.

    Generation is split into small parallel batches so the browser receives
    useful records as soon as the first batch is ready. Heartbeats keep the
    App Service connection active while the model is thinking. Nothing is
    persisted until the administrator reviews and imports the candidates.
    """
    if not settings.llm_configured():
        raise HTTPException(
            503,
            "LLM endpoint is not configured. Set AZURE_OPENAI_ENDPOINT, "
            "AZURE_OPENAI_API_KEY and LLM_DEPLOYMENT in .env",
        )

    existing_hashes = {h for (h,) in db.query(Script.normalized_hash).all()}
    existing_texts = [
        tn.normalize_arabic(t) for (t,) in db.query(Script.training_text).all()
    ]
    requested = params.count
    # Five records is a good balance: the first result arrives quickly without
    # turning a 30-record generation into 30 separate model requests.
    batch_size = min(5, requested)
    batch_counts = [
        min(batch_size, requested - offset)
        for offset in range(0, requested, batch_size)
    ]
    base_params = _generation_params(params, db)

    def line(event: dict) -> str:
        return json.dumps(event, ensure_ascii=False) + "\n"

    def generate_batch(index: int, count: int) -> tuple[int, list[dict]]:
        batch_params = {
            **base_params,
            "count": count,
            "batch_name": f"{params.batch_name} · part {index + 1}",
        }
        return index, llm_scripts.generate_scripts(batch_params, settings)

    def events():
        batch_hashes: set[str] = set()
        emitted = 0
        failures: list[str] = []
        executor = ThreadPoolExecutor(max_workers=min(3, len(batch_counts)))
        futures = {
            executor.submit(generate_batch, index, count)
            for index, count in enumerate(batch_counts)
        }
        try:
            yield line(
                {
                    "type": "start",
                    "model": settings.llm_deployment,
                    "requested": requested,
                    "batches": len(batch_counts),
                }
            )
            pending = set(futures)
            while pending and emitted < requested:
                done, pending = wait(pending, timeout=3, return_when=FIRST_COMPLETED)
                if not done:
                    yield line(
                        {
                            "type": "heartbeat",
                            "generated": emitted,
                            "requested": requested,
                        }
                    )
                    continue

                for future in done:
                    try:
                        batch_index, items = future.result()
                    except Exception as exc:
                        message = f"{type(exc).__name__}: {exc}"
                        failures.append(message)
                        yield line({"type": "batch_error", "message": message})
                        continue

                    for item in items:
                        if emitted >= requested:
                            break
                        candidate = llm_scripts.validate_item(
                            item, existing_hashes, existing_texts, batch_hashes
                        )
                        emitted += 1
                        yield line(
                            {
                                "type": "candidate",
                                "index": emitted - 1,
                                "batch": batch_index + 1,
                                "candidate": candidate,
                            }
                        )

            if emitted == 0 and failures:
                yield line(
                    {
                        "type": "error",
                        "message": "All generation batches failed: " + "; ".join(failures),
                    }
                )
            else:
                yield line(
                    {
                        "type": "complete",
                        "model": settings.llm_deployment,
                        "count": emitted,
                        "requested": requested,
                        "failed_batches": len(failures),
                    }
                )
        finally:
            for future in futures:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.patch("/{script_pk}", response_model=ScriptOut)
def patch_script(
    script_pk: int,
    payload: ScriptPatch,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    s = db.get(Script, script_pk)
    if not s:
        raise HTTPException(404, "Script not found")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(s, key, value)
    if "training_text" in data:
        s.normalized_hash = tn.normalized_hash(s.training_text)
        s.length_bucket = tn.length_bucket(s.training_text)
        s.word_count = tn.word_count(s.training_text)
        s.char_count = len(s.training_text)
    db.commit()
    return _script_out(db, s)


@router.post("/{script_pk}/flag", response_model=ScriptOut)
def flag_script(
    script_pk: int,
    payload: FlagIn,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    s = db.get(Script, script_pk)
    if not s:
        raise HTTPException(404, "Script not found")
    s.status = "flagged"
    if payload.reason:
        s.notes = (s.notes + "\n" if s.notes else "") + f"[flagged] {payload.reason}"
    db.commit()
    return _script_out(db, s)


@router.get("/{script_pk}", response_model=ScriptOut)
def get_script(script_pk: int, db: Session = Depends(get_db)):
    s = db.get(Script, script_pk)
    if not s:
        raise HTTPException(404, "Script not found")
    return _script_out(db, s)
