from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..models import (
    DIALECTS,
    DOMAINS,
    STYLES,
    Recording,
    RecordingSession,
    Script,
)

router = APIRouter(tags=["status"])


@router.get("/status")
def app_status(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    accepted = (
        db.query(func.count(Recording.id), func.coalesce(func.sum(Recording.duration_sec), 0.0))
        .filter(Recording.human_status == "accepted")
        .one()
    )
    active_session = (
        db.query(RecordingSession)
        .filter(RecordingSession.ended_at.is_(None))
        .order_by(RecordingSession.id.desc())
        .first()
    )
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "dataset_version": settings.dataset_version,
        "llm_configured": settings.llm_configured(),
        "llm_model": settings.llm_deployment or None,
        "asr_configured": settings.asr_configured(),
        "asr_model": settings.asr_deployment or None,
        "data_dir": str(settings.data_dir.resolve()),
        "scripts_total": db.query(func.count(Script.id)).scalar(),
        "recordings_total": db.query(func.count(Recording.id)).scalar(),
        "accepted_count": accepted[0],
        "accepted_duration_sec": round(accepted[1], 1),
        "active_session_id": active_session.id if active_session else None,
        "enums": {"styles": STYLES, "domains": DOMAINS, "dialects": DIALECTS},
        "export_sample_rate": settings.export_sample_rate,
    }


@router.get("/policy")
def policy_text():
    from pathlib import Path

    for candidate in [Path("POLICY.md"), Path("../POLICY.md")]:
        if candidate.exists():
            return {"text": candidate.read_text(encoding="utf-8")}
    return {"text": "POLICY.md not found."}
