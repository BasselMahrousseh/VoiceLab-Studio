# Data & storage

This document answers two questions precisely: **where is data saved**, and
**what is the database**.

## 1. Where everything is stored

All persistent data lives under a single **data directory**, `data/` by default,
resolved **relative to the process working directory** (the repo root when you
use `run_all.bat` / `run.ps1`). Override it with the `DATA_DIR` setting.

```
data/
├── voicelab.db                                  ← the SQL database (SQLite)
├── .auth_secret                                 ← HMAC secret for login tokens
├── audio/                                        ← recording MASTERS (never modified)
│   └── {speaker_key}/{script_id}/take_{NN}.wav       e.g. reader1/AE_FRIENDLY_000001/take_01.wav
└── exports/                                      ← generated dataset packages
    └── {batch_slug}/
        ├── dataset/
        │   ├── {speaker_key}/wavs/{script_id}.wav     mono PCM-16 @ target rate
        │   ├── metadata.csv
        │   ├── metadata.jsonl
        │   ├── qc_report.json
        │   └── dataset_card.md
        └── {batch_slug}.zip                            optional archive
```

- The whole `data/` directory is **gitignored** — it is runtime data, not source.
- **Masters** (`data/audio/...`) are 32-bit IEEE-float WAV, mono, at the capture
  rate (48 kHz). They are written once and never altered. Path format is defined
  in `backend/app/services/storage.py`.
- **Exports** (`data/exports/...`) are derived copies: resampled (default
  24 kHz), optionally silence-trimmed and normalized, written as mono PCM-16.
  Built by `backend/app/services/exporter.py`.
- **`.auth_secret`** is auto-generated on first run if `AUTH_SECRET` is not set,
  so login tokens survive restarts on one machine.

### Storage sizing (rough)

- Master WAV ≈ `48000 × 4 bytes/sec` ≈ **11.5 MB per minute** of audio (Float32).
- Export WAV @ 24 kHz PCM-16 ≈ `24000 × 2 bytes/sec` ≈ **2.9 MB per minute**.
- Database rows are small (text + metrics); the DB stays in the low MBs even for
  thousands of scripts and takes. Audio dominates disk usage.

To move audio off local disk (S3 / Azure Blob / OCI Object Storage), replace
`backend/app/services/storage.py` — it is the only module that reads/writes
master files, exposing `take_rel_path`, `save_master`, and `abs_audio_path`.

---

## 2. The database

- **ORM:** SQLAlchemy 2.0 (declarative models in `backend/app/models.py`).
- **Default engine:** **SQLite**, file `data/voicelab.db`, opened with
  `check_same_thread=False` (FastAPI serves requests across threads).
- **Connection string:** built in `config.py` as
  `sqlite:///{data_dir}/voicelab.db` unless `DATABASE_URL` is set.
- **Other backends:** set `DATABASE_URL` to use **PostgreSQL** or **Oracle** —
  the models are portable (see [Moving to PostgreSQL](#moving-to-postgresql)).
- **Schema management:** tables are created on startup via
  `Base.metadata.create_all`; a small SQLite-only helper
  (`db._migrate_sqlite`) adds columns introduced after a database was first
  created. Seed data (default admin, default dataset, default speaker) is
  inserted on first run.

### Entity-relationship overview

```mermaid
erDiagram
    USERS }o--|| DATASETS : "assigned to"
    USERS |o--|| SPEAKERS : "records as"
    DATASETS ||--o{ SCRIPTS : contains
    SPEAKERS ||--o{ RECORDING_SESSIONS : has
    RECORDING_SESSIONS ||--o{ RECORDINGS : contains
    SCRIPTS ||--o{ RECORDINGS : "recorded as"
    SPEAKERS ||--o{ RECORDINGS : "voiced by"
    EXPORT_BATCHES }o..o{ RECORDINGS : "snapshots accepted"
```

### Tables

**`users`** — operators of the studio.

| Column | Type | Notes |
| --- | --- | --- |
| id | int PK | |
| username | str, unique | login name |
| password_hash | str | `pbkdf2_sha256$iterations$salt$hash` |
| role | str | `admin` \| `recorder` |
| display_name | str | |
| active | bool | deactivated users cannot log in |
| speaker_id | int FK → speakers | the recorder's voice |
| dataset_id | int FK → datasets | the recorder's assigned dataset |
| created_at, last_login_at | datetime | |

**`datasets`** — a named set of scripts + recording guidance + plan.

| Column | Type | Notes |
| --- | --- | --- |
| id | int PK | |
| slug | str, unique | url-safe key |
| name, description | str | |
| instructions | text | shown to recorders |
| language, dialect | str | e.g. `ar-AE`, `emirati` |
| status | str | `active` \| `archived` |
| target_sample_count | int | planning target (samples) |
| target_avg_duration_sec | float | planning target (avg clip length) |
| created_at | datetime | |

**`speakers`** — a distinct voice.

| Column | Type | Notes |
| --- | --- | --- |
| id | int PK | |
| speaker_key | str, unique | folder name for that voice's audio |
| display_name, notes | str | |
| created_at | datetime | |

**`scripts`** — one sentence to record.

| Column | Type | Notes |
| --- | --- | --- |
| id | int PK | |
| script_id | str, unique | e.g. `AE_FRIENDLY_000001` |
| dataset_id | int FK → datasets | nullable (unassigned/legacy) |
| display_text | text | what the reader sees (digits allowed) |
| training_text | text | exact verbalization (numbers as words) |
| msa_equivalent | text | metadata only |
| language, dialect, style, domain | str | classification |
| tags | JSON | e.g. `["numbers","code_switch"]` |
| length_bucket, word_count, char_count | | derived |
| status | str | `new`/`recorded`/`done`/`flagged`/`retired` |
| active, priority | bool/int | queue control |
| source | str | `llm` \| `import` \| `manual` |
| generation_batch, generation_model | str | provenance for GenAI |
| notes, normalized_hash, created_at | | dedup + audit |

**`recording_sessions`** — groups takes by voice/device.

| Column | Type | Notes |
| --- | --- | --- |
| id | int PK | |
| speaker_id | int FK → speakers | |
| started_at, ended_at | datetime | open session has null `ended_at` |
| device_info | JSON | user agent / role |
| room_tone_dbfs, room_tone_status | float/str | booth noise floor check |
| notes | text | |

**`recordings`** — one take (audio + QC + review state).

| Column | Type | Notes |
| --- | --- | --- |
| id | int PK | |
| script_pk, session_id, speaker_id | int FK | |
| take_number | int | |
| rel_path | str | path under `data/audio/` |
| sample_rate, channels, sample_format | | master format |
| duration_sec, size_bytes, audio_sha256 | | file facts + dedup |
| qc_status | str | `passed`/`warning`/`failed` |
| qc_issues, qc_metrics | JSON | detector output |
| asr_status, asr_text, asr_cer, asr_wer, asr_detail | | advisory Whisper compare |
| human_status | str | `pending`/`accepted`/`rejected` |
| review_note | text | |
| final_text, text_edited | text/bool | exported transcript (may differ from script) |
| created_at, reviewed_at | datetime | |

**`export_batches`** — one export run.

| Column | Type | Notes |
| --- | --- | --- |
| id | int PK | |
| name | str | |
| params, stats | JSON | export options + aggregate quality stats |
| rel_path, zip_rel_path | str | output location under `data/exports/` |
| file_count, total_duration_sec | | totals |
| dataset_version, status, error | | `done` \| `failed` |
| created_at | datetime | |

> **Audio bytes are not stored in the database.** The DB holds a *reference*
> (`recordings.rel_path`) plus a SHA-256 and metrics; the WAV bytes live on disk
> under `data/audio/`. This keeps the database small and lets you back audio with
> object storage independently.

---

## 3. Backups

- **Everything that matters is in `data/`.** Back up the whole directory to
  capture the database + audio masters + exports together and consistently.
- SQLite is a single file (`voicelab.db`); copy it while the app is stopped, or
  use `sqlite3 data/voicelab.db ".backup ..."` for a hot copy.
- Master audio under `data/audio/` is the irreplaceable asset — exports can
  always be regenerated from masters + the database.

---

## 4. Moving to PostgreSQL

1. Provision a database and set, in `.env`:
   ```
   DATABASE_URL=postgresql+psycopg://user:pass@host:5432/lahja
   ```
   (install the matching driver, e.g. `psycopg`.)
2. Start the app once — `create_all` builds the tables. For evolving schemas on
   a real RDBMS, adopt Alembic migrations (the SQLite auto-column helper is
   intentionally SQLite-only).
3. Optionally move audio to object storage by swapping
   `backend/app/services/storage.py`.

The application code, routers, and services are unchanged — only configuration
differs.
