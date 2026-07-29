from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..models import Recording, RecordingSession, Script
from ..schemas import AcceptIn, RecordingOut, RejectIn
from ..services import storage
from ..services.audio_io import load_wav
from ..services.audio_qc import analyze_recording
from ..services.asr_verify import verify_against_script

router = APIRouter(prefix="/recordings", tags=["recordings"])


def _out(r: Recording) -> RecordingOut:
    return RecordingOut.model_validate(r)


def _refresh_script_status(db: Session, script: Script) -> None:
    """Script status derives from its recordings."""
    if script.status in ("flagged", "retired"):
        return
    statuses = [r.human_status for r in script.recordings]
    if "accepted" in statuses:
        script.status = "done"
    elif statuses:
        script.status = "recorded"
    else:
        script.status = "new"


@router.post("", response_model=RecordingOut)
def upload_recording(
    file: UploadFile = File(...),
    script_pk: int = Form(...),
    session_id: int = Form(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    script = db.get(Script, script_pk)
    if not script:
        raise HTTPException(404, "Script not found")
    session = db.get(RecordingSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.ended_at:
        raise HTTPException(409, "Session is already ended - start a new session")

    content = file.file.read()
    if not content:
        raise HTTPException(400, "Empty upload")
    try:
        audio = load_wav(content)
    except Exception as exc:
        raise HTTPException(400, f"Could not decode WAV: {exc}")

    take_number = (
        db.query(func.count(Recording.id)).filter(Recording.script_pk == script_pk).scalar()
        + 1
    )
    dataset_title = script.dataset.name if script.dataset else "unassigned"
    rel_path = storage.take_rel_path(
        session.speaker.speaker_key,
        dataset_title,
        script.script_id,
        take_number,
    )
    storage.save_master(settings, rel_path, content)

    qc = analyze_recording(audio, settings, raw_bytes=content)

    # duplicate-audio detection across the whole bank
    if qc.audio_sha256:
        dup = (
            db.query(Recording)
            .filter(Recording.audio_sha256 == qc.audio_sha256)
            .first()
        )
        if dup:
            qc.add(
                "warn",
                "duplicate_audio",
                f"Identical audio already exists ({dup.script.script_id} take {dup.take_number})",
            )
            if qc.status == "passed":
                qc.status = "warning"

    rec = Recording(
        script_pk=script_pk,
        session_id=session_id,
        speaker_id=session.speaker_id,
        take_number=take_number,
        rel_path=rel_path,
        sample_rate=audio.sample_rate,
        channels=audio.channels,
        sample_format=audio.subtype,
        duration_sec=round(audio.duration_sec, 3),
        size_bytes=len(content),
        audio_sha256=qc.audio_sha256,
        qc_status=qc.status,
        qc_issues=qc.issues,
        qc_metrics=qc.metrics,
    )
    db.add(rec)
    db.flush()
    _refresh_script_status(db, script)
    db.commit()
    db.refresh(rec)
    return _out(rec)


@router.get("", response_model=dict)
def list_recordings(
    human_status: str | None = None,
    qc_status: str | None = None,
    asr_status: str | None = None,
    script_pk: int | None = None,
    dataset_id: int | None = None,
    session_id: int | None = None,
    needs_review: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(Recording)
    if human_status:
        q = q.filter(Recording.human_status == human_status)
    if qc_status:
        q = q.filter(Recording.qc_status == qc_status)
    if asr_status:
        q = q.filter(Recording.asr_status == asr_status)
    if script_pk:
        q = q.filter(Recording.script_pk == script_pk)
    if dataset_id:
        q = q.join(Script, Recording.script_pk == Script.id).filter(
            Script.dataset_id == dataset_id
        )
    if session_id:
        q = q.filter(Recording.session_id == session_id)
    if needs_review:
        # undecided takes, plus accepted ones that QC/ASR still doubts;
        # rejected takes are settled and stay out of the attention queue
        suspect = (Recording.qc_status != "passed") | (
            Recording.asr_status.in_(["minor_mismatch", "major_mismatch"])
        )
        q = q.filter(
            (Recording.human_status == "pending")
            | ((Recording.human_status == "accepted") & suspect)
        )
    total = q.count()
    items = q.order_by(Recording.id.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [_out(r) for r in items]}


@router.get("/{rec_id}", response_model=RecordingOut)
def get_recording(rec_id: int, db: Session = Depends(get_db)):
    r = db.get(Recording, rec_id)
    if not r:
        raise HTTPException(404, "Recording not found")
    return _out(r)


@router.get("/{rec_id}/audio")
def recording_audio(
    rec_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    r = db.get(Recording, rec_id)
    if not r:
        raise HTTPException(404, "Recording not found")
    try:
        content = storage.read_master(settings, r.rel_path)
    except Exception as exc:
        raise HTTPException(404, f"Audio file unavailable: {exc}")
    filename = r.rel_path.rsplit("/", 1)[-1]
    return Response(
        content,
        media_type="audio/wav",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/{rec_id}/accept", response_model=RecordingOut)
def accept_recording(rec_id: int, payload: AcceptIn, db: Session = Depends(get_db)):
    r = db.get(Recording, rec_id)
    if not r:
        raise HTTPException(404, "Recording not found")
    if r.qc_status == "failed" and not payload.force:
        raise HTTPException(
            409,
            "Automatic QC failed. Re-record this take or explicitly use Save anyway.",
        )
    r.human_status = "accepted"
    r.reviewed_at = datetime.now(timezone.utc)
    r.forced_save = r.qc_status == "failed" and payload.force
    forced_note = "Saved anyway despite failed automatic QC."
    r.review_note = (
        f"{forced_note} {payload.note}".strip() if r.forced_save else payload.note
    )
    if payload.final_text is not None and payload.final_text.strip() != r.script.training_text:
        r.final_text = payload.final_text.strip()
        r.text_edited = True
    else:
        r.final_text = r.script.training_text
        r.text_edited = False
    _refresh_script_status(db, r.script)
    db.commit()
    db.refresh(r)
    return _out(r)


@router.post("/{rec_id}/reject", response_model=RecordingOut)
def reject_recording(
    rec_id: int,
    payload: RejectIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    r = db.get(Recording, rec_id)
    if not r:
        raise HTTPException(404, "Recording not found")
    # If the recorder rejects a take (restart/skip), remove the uploaded master
    # immediately so blob storage isn't polluted with unaccepted takes.
    storage.delete_master(settings, r.rel_path)
    r.human_status = "rejected"
    r.reviewed_at = datetime.now(timezone.utc)
    r.review_note = payload.note
    _refresh_script_status(db, r.script)
    db.commit()
    db.refresh(r)
    return _out(r)


@router.post("/{rec_id}/verify", response_model=RecordingOut)
def verify_recording(
    rec_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    r = db.get(Recording, rec_id)
    if not r:
        raise HTTPException(404, "Recording not found")
    if not settings.asr_configured():
        raise HTTPException(
            503,
            "ASR endpoint is not configured. Set ASR_DEPLOYMENT (and endpoint/key "
            "if different from the LLM resource) in .env",
        )
    try:
        wav = storage.read_master(settings, r.rel_path)
    except Exception as exc:
        raise HTTPException(404, f"Audio file unavailable: {exc}")
    language = {"ar-AE": "ar", "en-US": "en", "mixed": ""}.get(
        r.script.language, settings.asr_language
    )
    result = verify_against_script(
        wav, r.script.training_text, settings, language=language
    )
    r.asr_status = result["status"]
    r.asr_text = result["asr_text"]
    r.asr_cer = result["cer"]
    r.asr_wer = result["wer"]
    r.asr_detail = result["detail"]
    db.commit()
    db.refresh(r)
    return _out(r)
