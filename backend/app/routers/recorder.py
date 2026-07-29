"""Endpoints backing the simplified recorder view.

A recorder is a User with role ``recorder`` linked to a Speaker (their voice)
and a Dataset. These endpoints answer "what should I read next?" scoped to that
recorder's own dataset and voice, and keep an open recording session for them.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..deps import get_current_user
from ..models import Recording, RecordingSession, Script, User
from ..schemas import (
    PerformanceDashboardOut,
    RecorderContextOut,
    RecorderDeviceIn,
    RecorderSkipIn,
    RecorderSkipOut,
    ScriptOut,
    SpeakerOut,
)
from ..services import analytics as analytics_svc
from ..services import storage
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


def _log_skip(db: Session, user: User, script: Script) -> None:
    from ..models import ScriptSkip

    db.add(
        ScriptSkip(
            speaker_id=user.speaker_id,  # type: ignore[arg-type]
            dataset_id=script.dataset_id,
            script_id=script.script_id or "",
            display_text=(script.display_text or "")[:500],
        )
    )


def _remove_skipped_script(db: Session, settings: Settings, user: User, script: Script) -> None:
    """Remove a skipped sentence from the active corpus.

    If any accepted recordings already exist for this script (another speaker may
    have completed it), soft-retire instead of hard-deleting so accepted audio
    stays valid. Otherwise delete recordings, staging/master audio, and the
    script row so downloads and dataset counts no longer include it.
    """
    _log_skip(db, user, script)
    recordings = db.query(Recording).filter(Recording.script_pk == script.id).all()
    has_accepted = any(r.human_status == "accepted" for r in recordings)
    if has_accepted:
        script.active = False
        script.status = "retired"
        note = "[skipped/retired by recorder]"
        script.notes = f"{script.notes}\n{note}".strip() if script.notes else note
        db.commit()
        return

    audio_paths = list(dict.fromkeys(r.rel_path for r in recordings if r.rel_path))
    if recordings:
        db.query(Recording).filter(
            Recording.id.in_([r.id for r in recordings])
        ).delete(synchronize_session=False)
    db.delete(script)
    db.commit()

    for rel_path in audio_paths:
        try:
            storage.delete_pending(settings, rel_path)
        except Exception:
            pass
        try:
            storage.delete_master(settings, rel_path)
        except Exception:
            pass


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
    nxt = _next_for(db, user, exclude_id=exclude_id)
    return _script_out(db, nxt) if nxt else None


@router.post("/skip", response_model=RecorderSkipOut)
def recorder_skip(
    payload: RecorderSkipIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """Skip a sentence by removing it from the dataset, then return the next one.

    Unrecorded / non-accepted scripts are deleted from the database (and any
    pending takes cleaned up). Scripts that already have accepted recordings are
    retired instead, so they leave the queue and CSV export but keep history.
    """
    _require_recorder(user)
    _ensure_session(db, user)
    script = db.get(Script, payload.script_id)
    if not script or script.dataset_id != user.dataset_id:
        raise HTTPException(404, "Script not found in your dataset")
    _remove_skipped_script(db, settings, user, script)
    nxt = _next_for(db, user)
    return RecorderSkipOut(
        next_script=_script_out(db, nxt) if nxt else None,
        progress=_progress(db, user),
    )


@router.get("/progress")
def recorder_progress(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_recorder(user)
    return _progress(db, user)


@router.get("/dashboard", response_model=PerformanceDashboardOut)
def recorder_dashboard(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    language: str | None = None,
    dialect: str | None = None,
    human_status: str | None = None,
    session_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Personal performance dashboard for the logged-in recorder."""
    _require_recorder(user)
    filters = analytics_svc.AnalyticsFilter(
        date_from=date_from,
        date_to=date_to,
        dataset_id=user.dataset_id,
        language=language,
        dialect=dialect,
        human_status=human_status,
        session_id=session_id,
    )
    try:
        return analytics_svc.build_dashboard(db, user, filters, include_charts=True)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/session-summary")
def recorder_session_summary(
    session_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Summary for the current (or specified) recording session."""
    _require_recorder(user)
    if session_id:
        session = db.get(RecordingSession, session_id)
        if not session or session.speaker_id != user.speaker_id:
            raise HTTPException(404, "Session not found")
    else:
        session = _ensure_session(db, user)
    summary = analytics_svc._session_summary(db, session)
    if not summary:
        raise HTTPException(404, "No session")
    return summary


@router.post("/session-device")
def recorder_session_device(
    payload: RecorderDeviceIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Attach browser / microphone metadata to the open session."""
    _require_recorder(user)
    session = _ensure_session(db, user)
    info = dict(session.device_info or {})
    info["role"] = "recorder"
    for key, value in payload.model_dump(exclude_none=True).items():
        info[key] = value
    session.device_info = info
    db.commit()
    db.refresh(session)
    return {"session_id": session.id, "device_info": session.device_info}
