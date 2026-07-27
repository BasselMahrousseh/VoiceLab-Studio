from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Enumerated string values (kept as plain strings for flexibility; validated
# in the API layer so new styles/domains can be added without migrations).
# ---------------------------------------------------------------------------
STYLES = ["neutral", "friendly", "formal", "apologetic", "explanatory", "energetic"]
DIALECTS = ["emirati", "msa", "mixed", "english"]
LANGUAGES = ["ar-AE", "en-US", "mixed"]
DOMAINS = [
    "customer_support",
    "telecom",
    "billing",
    "technical_support",
    "sales",
    "numbers_dates",
    "general",
    "other",
]
SCRIPT_STATUSES = ["new", "recorded", "done", "flagged", "retired"]
QC_STATUSES = ["passed", "warning", "failed"]
HUMAN_STATUSES = ["pending", "accepted", "rejected"]
ASR_STATUSES = ["not_run", "match", "minor_mismatch", "major_mismatch", "error"]
ROLES = ["admin", "recorder"]


class AppSetting(Base):
    """Small database-backed settings that administrators edit in the UI."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class User(Base):
    """An operator of the studio.

    * ``admin``    — data scientist: builds datasets, manages recorders, reviews
      and exports. Sees the full app.
    * ``recorder`` — reads scripts aloud and saves takes. Linked to a Speaker
      (their voice) and an assigned Dataset; sees only the recording view.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="recorder", index=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    # recorders are tied to one voice and one dataset
    speaker_id: Mapped[int | None] = mapped_column(ForeignKey("speakers.id"), nullable=True)
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("datasets.id"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    speaker: Mapped["Speaker | None"] = relationship()
    dataset: Mapped["Dataset | None"] = relationship()


class Dataset(Base):
    """A named collection of scripts to record, with recording guidance.

    ``instructions`` is shown to recorders before/while they record — the
    "few instructions" that keep delivery consistent (room, mic distance,
    dialect, pace, what to do on a stumble…).
    """

    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(16), default="ar-AE")
    # A dataset may intentionally contain Arabic, English and code-switched
    # utterances. Every Script still carries its own exact language tag.
    languages: Mapped[list] = mapped_column(JSON, default=lambda: ["ar-AE"])
    dialect: Mapped[str] = mapped_column(String(24), default="emirati")
    # Dataset-specific additions layered on top of the global text policy.
    text_policy: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | archived
    # Planning targets set by the data scientist (used for hour projections and
    # to steer GenAI sentence length; not hard limits).
    target_sample_count: Mapped[int] = mapped_column(Integer, default=0)
    target_avg_duration_sec: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    scripts: Mapped[list["Script"]] = relationship(back_populates="dataset")


class Speaker(Base):
    __tablename__ = "speakers"

    id: Mapped[int] = mapped_column(primary_key=True)
    speaker_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    sessions: Mapped[list["RecordingSession"]] = relationship(back_populates="speaker")


class Script(Base):
    __tablename__ = "scripts"

    id: Mapped[int] = mapped_column(primary_key=True)
    script_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    dataset_id: Mapped[int | None] = mapped_column(
        ForeignKey("datasets.id"), nullable=True, index=True
    )

    # What the speaker sees (may contain digits, Latin brand names, etc.)
    display_text: Mapped[str] = mapped_column(Text)
    # Exact intended verbalization — the transcript paired with the audio.
    training_text: Mapped[str] = mapped_column(Text)
    # Optional MSA equivalent, stored as supplementary metadata only.
    msa_equivalent: Mapped[str | None] = mapped_column(Text, nullable=True)

    language: Mapped[str] = mapped_column(String(16), default="ar-AE")
    dialect: Mapped[str] = mapped_column(String(24), default="emirati", index=True)
    style: Mapped[str] = mapped_column(String(24), default="neutral", index=True)
    domain: Mapped[str] = mapped_column(String(48), default="general", index=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    length_bucket: Mapped[str] = mapped_column(String(12), default="medium")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    char_count: Mapped[int] = mapped_column(Integer, default=0)

    status: Mapped[str] = mapped_column(String(16), default="new", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)

    source: Mapped[str] = mapped_column(String(16), default="manual")  # llm|import|manual
    generation_batch: Mapped[str | None] = mapped_column(String(120), nullable=True)
    generation_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")  # pronunciation hints, flag reasons

    normalized_hash: Mapped[str] = mapped_column(String(64), index=True, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    dataset: Mapped["Dataset | None"] = relationship(back_populates="scripts")
    recordings: Mapped[list["Recording"]] = relationship(back_populates="script")


class RecordingSession(Base):
    __tablename__ = "recording_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    speaker_id: Mapped[int] = mapped_column(ForeignKey("speakers.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    device_info: Mapped[dict] = mapped_column(JSON, default=dict)
    room_tone_dbfs: Mapped[float | None] = mapped_column(Float, nullable=True)
    room_tone_status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # ok|warn
    notes: Mapped[str] = mapped_column(Text, default="")

    speaker: Mapped[Speaker] = relationship(back_populates="sessions")
    recordings: Mapped[list["Recording"]] = relationship(back_populates="session")


class Recording(Base):
    __tablename__ = "recordings"

    id: Mapped[int] = mapped_column(primary_key=True)
    script_pk: Mapped[int] = mapped_column(ForeignKey("scripts.id"), index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("recording_sessions.id"), index=True)
    speaker_id: Mapped[int] = mapped_column(ForeignKey("speakers.id"), index=True)
    take_number: Mapped[int] = mapped_column(Integer, default=1)

    rel_path: Mapped[str] = mapped_column(String(512))  # relative to data/audio
    sample_rate: Mapped[int] = mapped_column(Integer, default=0)
    channels: Mapped[int] = mapped_column(Integer, default=1)
    sample_format: Mapped[str] = mapped_column(String(24), default="")
    duration_sec: Mapped[float] = mapped_column(Float, default=0.0)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    audio_sha256: Mapped[str] = mapped_column(String(64), index=True, default="")

    qc_status: Mapped[str] = mapped_column(String(12), default="failed", index=True)
    qc_issues: Mapped[list] = mapped_column(JSON, default=list)
    qc_metrics: Mapped[dict] = mapped_column(JSON, default=dict)

    asr_status: Mapped[str] = mapped_column(String(20), default="not_run", index=True)
    asr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    asr_cer: Mapped[float | None] = mapped_column(Float, nullable=True)
    asr_wer: Mapped[float | None] = mapped_column(Float, nullable=True)
    asr_detail: Mapped[dict] = mapped_column(JSON, default=dict)

    human_status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
    # True when a human explicitly overrides a failed automatic QC result.
    # The original qc_status/issues remain unchanged for auditability.
    forced_save: Mapped[bool] = mapped_column(Boolean, default=False)
    # Transcript exported with this audio. Defaults to the script's training
    # text at accept time; reviewers may adjust it to match what was spoken.
    final_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_edited: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    script: Mapped[Script] = relationship(back_populates="recordings")
    session: Mapped[RecordingSession] = relationship(back_populates="recordings")
    speaker: Mapped[Speaker] = relationship()


class ExportBatch(Base):
    __tablename__ = "export_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    rel_path: Mapped[str] = mapped_column(String(512), default="")  # relative to data/exports
    zip_rel_path: Mapped[str] = mapped_column(String(512), default="")
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    total_duration_sec: Mapped[float] = mapped_column(Float, default=0.0)
    dataset_version: Mapped[str] = mapped_column(String(24), default="v1")
    status: Mapped[str] = mapped_column(String(16), default="done")  # done|failed
    error: Mapped[str] = mapped_column(Text, default="")
