# Technology stack

A deliberately small, mostly-standard stack. No message queue, no cache server,
no container runtime required; one Python process and a static SPA.

## Overview

| Layer | Technology |
| --- | --- |
| Frontend | React 18 + TypeScript 5, built with Vite 5; hand-written CSS |
| Audio capture | Web Audio API (`AudioWorklet`, `AnalyserNode`) |
| Backend | Python 3.11+, FastAPI, served by Uvicorn (ASGI) |
| Data validation | Pydantic v2 + pydantic-settings |
| Database | SQLAlchemy 2.0 ORM → SQLite (default) / PostgreSQL / Oracle |
| Audio DSP | NumPy, SciPy, soundfile (libsndfile), pyloudnorm |
| Text / QC | rapidfuzz, num2words, Python `re` |
| AI | `openai` SDK → Azure OpenAI (GPT-5.6-sol Responses API; Whisper ASR) |
| Auth | Python stdlib only (`hashlib` PBKDF2, `hmac`, `secrets`) |
| Tests | pytest |

---

## Backend (`backend/requirements.txt`)

| Package | Version (min) | Role & why |
| --- | --- | --- |
| **fastapi** | 0.115+ | REST framework — typed routes, dependency injection, automatic OpenAPI docs at `/docs`. |
| **uvicorn[standard]** | 0.30+ | ASGI server that runs FastAPI; also serves the built SPA as static files. |
| **python-multipart** | 0.0.9+ | Parses `multipart/form-data` for WAV file uploads. |
| **sqlalchemy** | 2.0+ | ORM and SQL toolkit; DB-agnostic models (SQLite/Postgres/Oracle). |
| **pydantic** | 2.7+ | Request/response schema validation and serialization. |
| **pydantic-settings** | 2.3+ | Loads configuration from `.env` / environment with typed fields. |
| **numpy** | 1.26+ | Numeric core for all audio analysis and QC math. |
| **scipy** | 1.11+ | High-quality polyphase resampling (`resample_poly`) and signal helpers. |
| **soundfile** | 0.12+ | WAV read/write via libsndfile — no ffmpeg dependency. |
| **pyloudnorm** | 0.1.1+ | Integrated-loudness (LUFS) normalization at export. |
| **rapidfuzz** | 3.6+ | Fast fuzzy matching for near-duplicate script detection. |
| **num2words** | 0.5.13+ | Converts digits to Arabic words for the `training_text` transcript. |
| **openai** | 1.40+ (2.x used) | Azure OpenAI client — Responses API for GPT-5.6-sol, Whisper for ASR. |
| **httpx** | 0.27+ | HTTP client used by the OpenAI SDK. |
| **pytest** | 8.0+ | Test runner (text normalization, QC detectors, full API/auth/recorder E2E). |

**Notably absent:** any auth/crypto library. Password hashing and token signing
use only the Python standard library (`hashlib.pbkdf2_hmac`, `hmac`, `secrets`),
avoiding native build steps (e.g. bcrypt) on Windows. See
`backend/app/services/auth.py`.

### Python version

3.11+ is expected (modern typing syntax such as `X | None` and
`list[str]` is used throughout). The project ships a local virtual environment
under `.venv/`.

---

## Frontend (`frontend/package.json`)

| Package | Version | Role & why |
| --- | --- | --- |
| **react** / **react-dom** | 18.3 | UI library. |
| **react-router-dom** | 6.26 | Client-side routing and role-based navigation. |
| **typescript** | 5.5 | Static typing across the SPA; types mirror backend schemas. |
| **vite** | 5.4 | Dev server (HMR, `/api` proxy) and production bundler. |
| **@vitejs/plugin-react** | 4.3 | React fast-refresh + JSX transform for Vite. |

- **No component/UI framework and no CSS framework** — the interface is plain
  React with hand-written CSS (`src/styles.css`) using CSS custom properties for
  the e& light theme. This keeps the bundle small (~75 kB gzipped JS) and the
  styling fully under control.
- **No client state library** — React local state plus one auth context
  (`src/auth.tsx`); server data is fetched on demand through `src/api.ts`.
- **Web Audio API** provides lossless capture: a custom `AudioWorklet` collects
  Float32 PCM (`src/audio/recorder.ts`) and `wav.ts` encodes it to a WAV blob in
  the browser.

---

## Database

SQLAlchemy 2.0 ORM with a configurable backend:

- **Default — SQLite:** a single file at `data/voicelab.db`, opened with
  `check_same_thread=False`. Zero setup; ideal for a single-machine studio.
- **PostgreSQL / Oracle:** set `DATABASE_URL` (e.g.
  `postgresql+psycopg://user:pass@host/db`). The models are portable.

A light auto-migration adds newly introduced columns on SQLite at startup
(`db._migrate_sqlite`). For production RDBMS backends, use a real migration tool
(e.g. Alembic). Full schema in [DATA_AND_STORAGE.md](DATA_AND_STORAGE.md).

---

## Azure OpenAI

Script generation calls **GPT-5.6-sol** through the Azure OpenAI
**Responses API** (`client.responses.create`, `POST /openai/responses`). Because
gpt-5.x models use the Responses API rather than classic Chat Completions, the
service (`services/llm_scripts.py`) selects the API by `LLM_API_STYLE`:

- `auto` (default) — try the Responses API, fall back to Chat Completions.
- `responses` — force the Responses API.
- `chat` — force Chat Completions (for older deployments).

Configuration (`.env`):

```
LLM_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
AZURE_OPENAI_API_KEY=<key>
AZURE_OPENAI_API_VERSION=2025-04-01-preview
LLM_DEPLOYMENT=gpt-5.6-sol
```

Any **OpenAI-compatible** endpoint also works via `LLM_PROVIDER=openai` +
`OPENAI_BASE_URL`. **ASR** (Whisper) is optional and advisory-only; when
unconfigured, generation/ASR features simply report "not configured" and the
recording/QC/export workflow is fully functional without them.

---

## Build & run tooling

- **run_all.bat** — Windows one-click launcher (bootstraps venv + npm on first
  run, builds the SPA, starts the server, opens the browser).
- **run.ps1 / run_dev.ps1** — production / development PowerShell scripts.
- **Vite** builds the SPA to `frontend/dist`, which FastAPI serves at `/`.
