from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Speaker
from ..schemas import SpeakerCreate, SpeakerOut

router = APIRouter(prefix="/speakers", tags=["speakers"])


@router.get("", response_model=list[SpeakerOut])
def list_speakers(db: Session = Depends(get_db)):
    return db.query(Speaker).order_by(Speaker.id).all()


@router.post("", response_model=SpeakerOut)
def create_speaker(payload: SpeakerCreate, db: Session = Depends(get_db)):
    if db.query(Speaker).filter_by(speaker_key=payload.speaker_key).first():
        raise HTTPException(409, f"Speaker key '{payload.speaker_key}' already exists")
    speaker = Speaker(**payload.model_dump())
    db.add(speaker)
    db.commit()
    db.refresh(speaker)
    return speaker
