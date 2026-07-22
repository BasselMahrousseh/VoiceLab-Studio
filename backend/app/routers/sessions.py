from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..models import Recording, RecordingSession, Speaker
from ..schemas import SessionOut, SessionStart
from ..services.audio_io import load_wav
from ..services.audio_qc import analyze_room_tone

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _with_counts(db: Session, s: RecordingSession) -> SessionOut:
    out = SessionOut.model_validate(s)
    out.recording_count = (
        db.query(func.count(Recording.id)).filter(Recording.session_id == s.id).scalar()
    )
    out.accepted_count = (
        db.query(func.count(Recording.id))
        .filter(Recording.session_id == s.id, Recording.human_status == "accepted")
        .scalar()
    )
    return out


@router.get("", response_model=list[SessionOut])
def list_sessions(limit: int = 50, db: Session = Depends(get_db)):
    sessions = (
        db.query(RecordingSession).order_by(RecordingSession.id.desc()).limit(limit).all()
    )
    return [_with_counts(db, s) for s in sessions]


@router.get("/active", response_model=SessionOut | None)
def active_session(db: Session = Depends(get_db)):
    s = (
        db.query(RecordingSession)
        .filter(RecordingSession.ended_at.is_(None))
        .order_by(RecordingSession.id.desc())
        .first()
    )
    return _with_counts(db, s) if s else None


@router.post("/start", response_model=SessionOut)
def start_session(payload: SessionStart, db: Session = Depends(get_db)):
    speaker = db.get(Speaker, payload.speaker_id)
    if not speaker:
        raise HTTPException(404, "Speaker not found")
    # close this speaker's dangling open sessions (other recorders may be live)
    for s in (
        db.query(RecordingSession)
        .filter(
            RecordingSession.ended_at.is_(None),
            RecordingSession.speaker_id == payload.speaker_id,
        )
        .all()
    ):
        s.ended_at = datetime.now(timezone.utc)
    session = RecordingSession(
        speaker_id=payload.speaker_id,
        device_info=payload.device_info,
        notes=payload.notes,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _with_counts(db, session)


@router.post("/{session_id}/end", response_model=SessionOut)
def end_session(session_id: int, db: Session = Depends(get_db)):
    s = db.get(RecordingSession, session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    if not s.ended_at:
        s.ended_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(s)
    return _with_counts(db, s)


@router.post("/{session_id}/room-tone")
def room_tone(
    session_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    s = db.get(RecordingSession, session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    try:
        audio = load_wav(file.file.read())
    except Exception as exc:
        raise HTTPException(400, f"Could not decode audio: {exc}")
    result = analyze_room_tone(audio, settings)
    s.room_tone_dbfs = result["room_tone_dbfs"]
    s.room_tone_status = result["status"]
    db.commit()
    return result
