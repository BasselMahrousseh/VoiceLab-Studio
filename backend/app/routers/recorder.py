"""Endpoints backing the simplified recorder view.

A recorder is a User with role ``recorder`` linked to a Speaker (their voice)
and a Dataset. These endpoints answer "what should I read next?" scoped to that
recorder's own dataset and voice, and keep an open recording session for them.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Recording, RecordingSession, Script, User
from ..schemas import DatasetOut, RecorderContextOut, ScriptOut, SpeakerOut
from .datasets import dataset_out
from .scripts import _script_out

router = APIRouter(prefix="/recorder", tags=["recorder"])


def _require_recorder(user: User) -> None:
    if user.role != "recorder":
        raise HTTPException(403, "This view is for recorder accounts")
    if not user.speaker_id:
        raise HTTPException(400, "No voice (speaker) is linked to your account")
    if not user.dataset_id:
        raise HTTPException(400, "You have not been assigned to a dataset yet")


def _ensure_session(db: Session, user: User) -> RecordingSession:
    session = (
        db.query(RecordingSession)
        .filter(
            RecordingSession.speaker_id == user.speaker_id,
            RecordingSession.ended_at.is_(None),
        )
        .order_by(RecordingSession.id.desc())
        .first()
    )
    if session:
        return session
    session = RecordingSession(speaker_id=user.speaker_id, device_info={"role": "recorder"})
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _accepted_script_ids(db: Session, speaker_id: int):
    return db.query(Recording.script_pk).filter(
        Recording.speaker_id == speaker_id, Recording.human_status == "accepted"
    )


def _next_for(db: Session, user: User, exclude_id: int | None = None) -> Script | None:
    q = db.query(Script).filter(
        Script.dataset_id == user.dataset_id,
        Script.active.is_(True),
        Script.status.notin_(["flagged", "retired"]),
        Script.id.notin_(_accepted_script_ids(db, user.speaker_id)),
    )
    if exclude_id:
        q = q.filter(Script.id != exclude_id)
    return q.order_by(Script.priority, Script.id).first()


def _progress(db: Session, user: User) -> dict:
    base = db.query(func.count(Script.id)).filter(
        Script.dataset_id == user.dataset_id,
        Script.active.is_(True),
        Script.status.notin_(["flagged", "retired"]),
    )
    total = base.scalar() or 0
    done = base.filter(Script.id.in_(_accepted_script_ids(db, user.speaker_id))).scalar() or 0
    return {"total": total, "done": done, "remaining": max(total - done, 0)}


@router.get("/context", response_model=RecorderContextOut)
def recorder_context(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_recorder(user)
    session = _ensure_session(db, user)
    nxt = _next_for(db, user)
    return RecorderContextOut(
        dataset=dataset_out(db, user.dataset) if user.dataset else None,
        speaker=SpeakerOut.model_validate(user.speaker) if user.speaker else None,
        session_id=session.id,
        progress=_progress(db, user),
        next_script=_script_out(db, nxt) if nxt else None,
        room_tone_dbfs=session.room_tone_dbfs,
        room_tone_status=session.room_tone_status,
    )


@router.get("/next", response_model=ScriptOut | None)
def recorder_next(
    exclude_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_recorder(user)
    nxt = _next_for(db, user, exclude_id)
    return _script_out(db, nxt) if nxt else None


@router.get("/progress")
def recorder_progress(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_recorder(user)
    return _progress(db, user)
