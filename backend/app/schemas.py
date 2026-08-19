from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- speakers ---------------------------------------------------------------
class SpeakerOut(ORMModel):
    id: int
    speaker_key: str
    display_name: str
    notes: str
    created_at: datetime


# --- auth & users -----------------------------------------------------------
class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(ORMModel):
    id: int
    username: str
    role: str
    display_name: str
    active: bool
    speaker_id: int | None
    dataset_id: int | None
    created_at: datetime
    last_login_at: datetime | None = None
    speaker: SpeakerOut | None = None
    dataset_name: str | None = None


class TokenOut(BaseModel):
    token: str
    user: UserOut


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=4, max_length=128)
    role: str = "recorder"  # admin | recorder
    display_name: str = ""
    dataset_id: int | None = None
    speaker_key: str = ""  # recorders: voice key, defaults to the username


class UserPatch(BaseModel):
    display_name: str | None = None
    active: bool | None = None
    dataset_id: int | None = None
    password: str | None = Field(default=None, min_length=4, max_length=128)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=4, max_length=128)


# --- datasets ---------------------------------------------------------------
class DatasetOut(ORMModel):
    id: int
    slug: str
    name: str
    description: str
    instructions: str
    language: str
    languages: list[str] = Field(default_factory=lambda: ["ar-AE"])
    dialect: str
    text_policy: str = ""
    status: str
    target_sample_count: int = 0
    target_avg_duration_sec: float = 0.0
    created_at: datetime
    script_count: int = 0
    accepted_count: int = 0
    accepted_duration_sec: float = 0.0
    recorder_count: int = 0


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    instructions: str = ""
    dialect: str = "emirati"
    language: str = "ar-AE"
    languages: list[str] = Field(default_factory=lambda: ["ar-AE"])
    text_policy: str = ""
    target_sample_count: int = 0
    target_avg_duration_sec: float = 0.0


class DatasetPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    instructions: str | None = None
    languages: list[str] | None = None
    dialect: str | None = None
    text_policy: str | None = None
    status: str | None = None
    target_sample_count: int | None = None
    target_avg_duration_sec: float | None = None


class AddScriptsIn(BaseModel):
    """Bulk-add scripts to a dataset from pasted text (one per line) or JSONL."""

    text: str = ""
    style: str = "neutral"
    domain: str = "general"
    dialect: str = "emirati"
    language: str = "auto"
    allow_warnings: bool = True


class RecorderContextOut(BaseModel):
    dataset: DatasetOut | None
    speaker: SpeakerOut | None
    session_id: int | None
    progress: dict
    next_script: "ScriptOut | None" = None
    room_tone_dbfs: float | None = None
    room_tone_status: str | None = None


class SpeakerCreate(BaseModel):
    speaker_key: str = Field(min_length=1, max_length=64)
    display_name: str = ""
    notes: str = ""


# --- sessions ----------------------------------------------------------------
class SessionOut(ORMModel):
    id: int
    speaker_id: int
    started_at: datetime
    ended_at: datetime | None
    device_info: dict
    room_tone_dbfs: float | None
    room_tone_status: str | None
    notes: str
    speaker: SpeakerOut | None = None
    recording_count: int = 0
    accepted_count: int = 0


class SessionStart(BaseModel):
    speaker_id: int
    device_info: dict = Field(default_factory=dict)
    notes: str = ""


# --- scripts -----------------------------------------------------------------
class ScriptOut(ORMModel):
    id: int
    script_id: str
    dataset_id: int | None = None
    display_text: str
    training_text: str
    msa_equivalent: str | None
    language: str
    dialect: str
    style: str
    domain: str
    tags: list
    length_bucket: str
    word_count: int
    char_count: int
    status: str
    active: bool
    priority: int
    source: str
    generation_batch: str | None
    generation_model: str | None
    notes: str
    created_at: datetime
    take_count: int = 0


class ScriptItemIn(BaseModel):
    display_text: str
    training_text: str | None = None
    msa_equivalent: str | None = None
    language: str = "auto"
    dialect: str = "emirati"
    style: str = "neutral"
    domain: str = "general"
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    priority: int = 100


class ScriptImportIn(BaseModel):
    items: list[ScriptItemIn]
    source: str = "import"
    generation_batch: str | None = None
    generation_model: str | None = None
    allow_warnings: bool = True


class ScriptPatch(BaseModel):
    display_text: str | None = None
    training_text: str | None = None
    msa_equivalent: str | None = None
    language: str | None = None
    dialect: str | None = None
    style: str | None = None
    domain: str | None = None
    tags: list[str] | None = None
    notes: str | None = None
    priority: int | None = None
    active: bool | None = None
    status: str | None = None


class GenerateParams(BaseModel):
    count: int = Field(default=20, ge=1, le=100)
    styles: list[str] = Field(default_factory=lambda: ["neutral"])
    genres: list[str] = Field(
        default_factory=lambda: [
            "transactional",
            "troubleshooting",
            "informational",
            "complaint",
            "advisory",
            "social",
        ]
    )
    domains: list[str] = Field(default_factory=lambda: ["customer_support"])
    languages: list[str] = Field(default_factory=lambda: ["ar-AE"])
    dialect: str = "emirati"
    length_mix: list[str] = Field(default_factory=lambda: ["short", "medium", "long"])
    coverage: list[str] = Field(default_factory=list)
    topics: str = ""
    brand_terms: str = ""
    batch_name: str = ""
    policy_text: str = ""
    # Target average spoken duration per clip (seconds); steers sentence length.
    avg_duration_sec: float = Field(default=0.0, ge=0, le=60)
    # Intended speaker gender for generation + Emirati consistency checks.
    speaker_gender: Literal["any", "male", "female"] = "any"
    # When true (default), reserve ~25% of the batch for non-telecom general talk.
    include_general: bool = True
    # Higher values increase lexical and structural variation. The LLM client
    # retries without this parameter for model deployments that do not support it.
    temperature: float = Field(default=1.3, ge=0.0, le=2.0)
    # Optional reproducibility control. Normal requests receive a fresh seed.
    variation_seed: int | None = Field(default=None, ge=0, le=2_147_483_647)

    @field_validator("speaker_gender", mode="before")
    @classmethod
    def _normalize_speaker_gender(cls, value: object) -> str:
        # Accept legacy aliases so older clients keep working.
        if value is None or value == "":
            return "any"
        raw = str(value).strip().lower()
        aliases = {
            "unspecified": "any",
            "none": "any",
            "neutral": "any",
            "masculine": "male",
            "m": "male",
            "man": "male",
            "feminine": "female",
            "f": "female",
            "woman": "female",
        }
        return aliases.get(raw, raw)


class FlagIn(BaseModel):
    reason: str = ""


class RecorderSkipIn(BaseModel):
    script_id: int


class RecorderSkipOut(BaseModel):
    next_script: ScriptOut | None = None
    progress: dict = Field(default_factory=dict)


# --- recordings ----------------------------------------------------------------
class RecordingOut(ORMModel):
    id: int
    script_pk: int
    session_id: int
    speaker_id: int
    take_number: int
    rel_path: str
    sample_rate: int
    channels: int
    sample_format: str
    duration_sec: float
    size_bytes: int
    qc_status: str
    qc_issues: list
    qc_metrics: dict
    asr_status: str
    asr_text: str | None
    asr_cer: float | None
    asr_wer: float | None
    asr_detail: dict
    human_status: str
    review_note: str
    forced_save: bool = False
    final_text: str | None
    text_edited: bool
    created_at: datetime
    reviewed_at: datetime | None
    script: ScriptOut | None = None


class AcceptIn(BaseModel):
    final_text: str | None = None  # reviewer-approved transcript override
    note: str = ""
    force: bool = False


class RejectIn(BaseModel):
    note: str = ""


# --- exports -------------------------------------------------------------------
class ExportParams(BaseModel):
    name: str = ""
    dataset_id: int | None = None
    sample_rate: int | None = None
    trim_silence: bool = True
    normalize: str = "none"  # none | peak | loudness
    target_lufs: float = -20.0
    dedupe_takes: bool = True
    include_qc_warning: bool = True
    styles: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    make_zip: bool = True


class PolicyUpdate(BaseModel):
    text: str = Field(min_length=1, max_length=50000)


class ExportOut(ORMModel):
    id: int
    name: str
    created_at: datetime
    params: dict
    stats: dict
    rel_path: str
    zip_rel_path: str
    file_count: int
    total_duration_sec: float
    dataset_version: str
    status: str
    error: str


# --- analytics / performance dashboard ---------------------------------------
class RecorderDeviceIn(BaseModel):
    """Client-reported browser / mic metadata for the open session."""

    browser: str | None = None
    userAgent: str | None = None
    deviceId: str | None = None
    deviceLabel: str | None = None
    microphone: str | None = None


class InsightOut(BaseModel):
    code: str
    level: str  # success | warn | info
    message: str


class AchievementOut(BaseModel):
    code: str
    icon: str
    title: str
    earned: bool
    detail: str = ""


class TrendOut(BaseModel):
    current: float | None = None
    previous: float | None = None
    delta: float | None = None
    direction: str = "stable"  # improving | stable | declining


class LeaderboardRowOut(BaseModel):
    user_id: int
    display_name: str
    username: str
    dataset_id: int | None = None
    dataset_name: str | None = None
    assigned: int = 0
    completed: int = 0
    remaining: int = 0
    skipped: int = 0
    accepted: int = 0
    acceptance_rate: float = 0.0
    avg_qc_score: float | None = None
    avg_time_per_script_sec: float | None = None
    hours_recorded: float = 0.0
    current_streak: int = 0
    total_recordings: int = 0


class PerformanceDashboardOut(BaseModel):
    """Single aggregated payload for recorder + admin performance views."""

    profile: dict
    progress: dict
    quality: dict
    activity: dict
    productivity: dict
    audio_quality: dict
    insights: list[InsightOut] = Field(default_factory=list)
    ai_insights: list[str] = Field(default_factory=list)
    achievements: list[AchievementOut] = Field(default_factory=list)
    session_summary: dict | None = None
    kpis: dict = Field(default_factory=dict)
    trends: dict = Field(default_factory=dict)
    charts: dict = Field(default_factory=dict)
    filters: dict = Field(default_factory=dict)


# Resolve forward reference to ScriptOut now that it is defined.
RecorderContextOut.model_rebuild()
