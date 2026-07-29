"""Application configuration.

All values can be overridden via environment variables or a `.env` file in the
working directory (see `.env.example` at the repo root). Standard Azure OpenAI
variable names (AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY) are used so an
existing deployment env file can be dropped in unchanged.
"""
import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


class Settings(BaseSettings):
    # env_file is overridable (tests point it at a nonexistent path for hermetic
    # runs). The .env file is treated as authoritative — see the source ordering
    # below — so the endpoint/key you configure here win over any ambient
    # AZURE_OPENAI_* variables left in the shell by other projects. For local
    # development, `.env.local` can override `.env` without changing the
    # deployment-oriented defaults checked into the environment file.
    model_config = SettingsConfigDict(
        env_file=os.environ.get("LAHJA_ENV_FILE") or (".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ):
        # Priority (first wins): explicit init args > .env file > OS env vars.
        return init_settings, dotenv_settings, env_settings, file_secret_settings

    # --- app ---
    app_name: str = "e& Lahja Studio"
    app_version: str = "0.3.1"
    dataset_version: str = "v2"
    host: str = "127.0.0.1"
    port: int = 8000

    # --- storage ---
    data_dir: Path = Path("data")
    # Pending takes are held here until the recorder clicks Save/Accept.
    # Defaults to a "pending" sub-folder inside data_dir.
    pending_dir: Path | None = None
    storage_backend: str = "local"  # "local" | "azure_blob"
    azure_storage_account_url: str = ""
    azure_storage_container: str = "voicelab"
    azure_storage_audio_prefix: str = "audio"
    azure_storage_export_prefix: str = "exports"
    azure_storage_backup_prefix: str = "database-backups"
    # Client ID of the user-assigned managed identity attached to App Service.
    azure_client_id: str = ""
    # Default: sqlite file inside data_dir. Set DATABASE_URL for Postgres/Oracle.
    database_url: str = ""

    # --- auth ---
    # HMAC secret for signing login tokens. Leave blank to auto-generate and
    # persist to data/.auth_secret (fine for a single-machine deployment).
    auth_secret: str = ""
    # Seeded on first run so an admin can log in immediately. Change the
    # password from the Team page after first login.
    default_admin_username: str = "admin"
    default_admin_password: str = "changeme"
    default_admin_name: str = "Data scientist"

    # --- default speaker (seeded on first run) ---
    default_speaker_key: str = "speaker_001"
    default_speaker_name: str = "Primary speaker"

    # --- script bank ---
    script_id_prefix: str = "AE"
    default_language: str = "ar-AE"

    # --- LLM for script generation (Azure OpenAI or any OpenAI-compatible API) ---
    llm_provider: str = "azure"  # "azure" | "openai"
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_api_version: str = "2024-10-21"
    llm_deployment: str = ""  # Azure deployment name or model name, e.g. gpt-5.6-sol
    openai_base_url: str = ""  # for llm_provider="openai" (OpenAI-compatible servers)
    openai_api_key: str = ""
    # Newer Azure models (gpt-5.x) use the Responses API; classic deployments use
    # Chat Completions. "auto" tries Responses first and falls back.
    llm_api_style: str = "auto"  # auto | responses | chat
    # Rough spoken words-per-second, used to turn a target average clip duration
    # into a target sentence length for generation and hour projections.
    llm_words_per_second: float = 2.3

    # --- ASR verification (Whisper on Azure OpenAI or OpenAI-compatible) ---
    # Falls back to the LLM endpoint/key when left empty (same Azure resource).
    asr_provider: str = "azure"  # "azure" | "openai"
    asr_deployment: str = ""  # e.g. "whisper"
    asr_azure_endpoint: str = ""
    asr_azure_api_key: str = ""
    asr_azure_api_version: str = ""
    asr_openai_base_url: str = ""
    asr_openai_api_key: str = ""
    realtime_asr_deployment: str = ""
    asr_language: str = "ar"
    # Compare digits as Arabic words before scoring (recommended: scripts often
    # contain digits that the speaker verbalizes).
    asr_verbalize_digits: bool = True
    # CER thresholds (on normalized text)
    asr_cer_match: float = 0.05
    asr_cer_minor: float = 0.15
    # Looser thresholds for code-switched lines (ASR is unreliable on Latin tokens)
    asr_cer_match_latin: float = 0.12
    asr_cer_minor_latin: float = 0.30

    # --- audio QC thresholds ---
    qc_hard_min_duration_sec: float = 0.8
    qc_hard_max_duration_sec: float = 25.0
    qc_warn_min_duration_sec: float = 2.0
    qc_warn_max_duration_sec: float = 13.0
    qc_clip_threshold: float = 0.9995  # |sample| considered clipped (float scale)
    qc_clip_warn_count: int = 4
    qc_clip_fail_ratio: float = 0.001
    qc_lead_trail_warn_sec: float = 1.5
    qc_abrupt_start_sec: float = 0.05
    qc_internal_silence_warn_sec: float = 2.0
    qc_speech_ratio_fail: float = 0.15
    qc_snr_warn_db: float = 30.0
    qc_snr_fail_db: float = 15.0
    qc_noise_floor_warn_dbfs: float = -50.0
    qc_rms_warn_low_dbfs: float = -32.0
    qc_rms_warn_high_dbfs: float = -12.0
    qc_dc_offset_warn: float = 0.02
    room_tone_warn_dbfs: float = -55.0

    # --- export defaults ---
    export_sample_rate: int = 24000
    export_trim_pad_sec: float = 0.2

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    @property
    def resolved_pending_dir(self) -> Path:
        return self.pending_dir if self.pending_dir else self.data_dir / "pending"

    @property
    def export_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        db_path = (self.data_dir / "voicelab.db").as_posix()
        return f"sqlite:///{db_path}"

    def llm_configured(self) -> bool:
        if not self.llm_deployment:
            return False
        if self.llm_provider == "azure":
            return bool(
                self.azure_openai_endpoint
                and (self.azure_openai_api_key or self.azure_client_id)
            )
        return bool(self.openai_base_url or self.openai_api_key)

    def asr_configured(self) -> bool:
        if not self.asr_deployment:
            return False
        if self.asr_provider == "azure":
            endpoint = self.asr_azure_endpoint or self.azure_openai_endpoint
            key = self.asr_azure_api_key or self.azure_openai_api_key
            return bool(endpoint and (key or self.azure_client_id))
        return bool(
            self.asr_openai_base_url
            or self.asr_openai_api_key
            or self.openai_api_key
        )

    def blob_storage_configured(self) -> bool:
        return (
            self.storage_backend == "azure_blob"
            and bool(self.azure_storage_account_url)
            and bool(self.azure_storage_container)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
