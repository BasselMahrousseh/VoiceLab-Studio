# e& Lahja Studio

A scripted **multilingual voice-recording and dataset-quality platform** for
building high-quality Arabic, English, and code-switched audio-text pairs for
TTS / voice-cloning fine-tuning, with first-class Emirati dialect governance.

Core pipeline:

```
admin builds a dataset (scripts + recording instructions) → assigns recorders
→ recorder logs in, reads each line, saves or restarts → automatic audio QC
→ admin review / re-record → optional ASR comparison → dataset packaging & export
```

## Accounts & roles

Login is required. Two roles:

- **Admin** (data scientist) — builds datasets, writes recording instructions,
  creates recorder accounts, and gets the full app (Datasets, Team, Studio,
  Script library, Review, Export, Settings).
- **Recorder** — reads scripts aloud in a stripped-down view: the next sentence,
  a big Record button, then **Save & next** or **Restart**. Each recorder is
  tied to one voice (Speaker) and one assigned dataset.

On first run a default admin is seeded — **`admin` / `changeme`** — change the
password from the **Team** page immediately. See the auth section in
[.env.example](.env.example) to customize the seed or pin the token secret.

## Documentation

Detailed technical docs live in [`docs/`](docs/README.md):

- [Architecture](docs/ARCHITECTURE.md) — components, request flows, audio pipeline, diagrams
- [Product reevaluation](docs/PRODUCT_REEVALUATION.md) — feature boundaries, v0.2 corrections, production priorities
- [Tech stack](docs/TECH_STACK.md) — every technology, versions, and rationale
- [Data & storage](docs/DATA_AND_STORAGE.md) — where data is saved, the database, full schema

## Quick start

```powershell
# 1. Backend deps (once)
python -m venv .venv
.venv\Scripts\pip install -r backend\requirements.txt

# 2. Frontend build (once, and after UI changes)
cd frontend; npm install; npm run build; cd ..

# 3. Configure endpoints (optional — app runs without them)
copy .env.example .env   # then edit

# 4. Run
.\run.ps1                # http://127.0.0.1:8000
```

Development mode (hot reload): `.\run_dev.ps1` starts uvicorn with `--reload`
plus the Vite dev server on http://localhost:5173 (proxying `/api`).

> **Microphone note:** browsers only allow mic capture on secure origins.
> `http://localhost` / `http://127.0.0.1` count as secure — record on the
> machine running the server, or put HTTPS in front for LAN access.

## Workflow

1. **Datasets page** (admin) — the project/work-unit owner. Create a dataset
   with its allowed languages, Arabic dialect, global + dataset-specific text
   policy, recording instructions, targets and scripts. Paste multilingual
   lines or generate reviewed candidates live with AI. Assign recorders here.
2. **Team page** (admin) — manage all users: add admins/recorders, reset
   passwords, enable/disable accounts, reassign a recorder's dataset.
3. **Recorder view** — what a recorder sees after login: the dataset's
   instructions, the next sentence to read, a Record button (Space), then
   **Save & next** (Enter) or **Restart** (R). Progress bar tracks completion.
4. **Script library** — search, filter, audit and edit utterances across
   datasets. Creation and AI generation stay on the owning dataset so scripts
   cannot lose their policy, language context, or project ownership.
5. **Studio page** — full-featured recording for admins: start a session, run a
   **room-tone check**, then record:
   one script at a time, Space to record/stop, live level meter with clip
   light, instant QC verdict, optional automatic Whisper comparison, Enter to
   accept, R to re-record, S to skip.
6. **Review page** — everything pending or flagged (QC warnings, ASR
   mismatches) with playback, metric details, script-vs-ASR diff, and
   transcript editing (reviewer-approved, marked `text_edited`).
7. **Export page** — select one dataset; accepted takes →
   `dataset/…/wavs/*.wav` (mono PCM-16 at
   the target rate) + `metadata.csv` + `metadata.jsonl` + `qc_report.json` +
   dataset card, optionally zipped.

## Key design decisions

- **Lossless capture.** The browser records raw PCM via an AudioWorklet — not
  `MediaRecorder`, which would compress to lossy Opus. Browser DSP (echo
  cancellation, noise suppression, auto-gain) is explicitly disabled: those
  processors damage voice timbre, which matters more for TTS than for calls.
- **Float32 masters, derived exports.** Takes are stored as float32 WAV at the
  interface rate (usually 48 kHz). Resampling to the target rate (default
  24 kHz), silence trimming and normalization happen only at export, so you
  can re-export for any future model without touching masters.
- **Two text layers.** `display_text` (what the speaker reads; digits OK) vs
  `training_text` (exact verbalization; numbers as words). See
  [POLICY.md](POLICY.md).
- **Emirati is never rewritten to MSA.** MSA equivalents live in metadata only.
- **ASR is advisory.** Whisper output is normalized (diacritics, hamza folding,
  digit verbalization on both sides) and scored with CER/WER against the
  script; thresholds are looser for code-switched lines. It flags mismatches —
  humans decide. It never replaces the transcript.
- **QC every take**: duration bounds, clipping, DC offset, LUFS, speech ratio,
  lead/trail/internal silence, noise floor, SNR, level windows, duplicate audio
  detection, format validation. Hard failures block one-click accept in the
  studio; warnings route to Review.

## Configuration

All settings via `.env` (see [.env.example](.env.example)). The LLM and ASR
sections accept an **Azure OpenAI** resource (standard `AZURE_OPENAI_*`
variables + deployment names) or any **OpenAI-compatible** endpoint. Without
them the recording/QC/export workflow is fully functional.

Storage is local by default: SQLite database + WAV files under `data/`. Set
`DATABASE_URL` for Postgres (or Oracle via SQLAlchemy) when you outgrow it;
swap `backend/app/services/storage.py` for object storage.

## Testing

```powershell
.venv\Scripts\python -m pytest backend\tests -q
```

Covers text normalization, QC detectors (clean/clipped/silent/short synthetic
audio), and the full API flow: import → session → upload → QC → accept with
transcript edit → export (file layout, sample rate, metadata content).

## Architecture

```
backend/app
  config.py        settings (.env), auth seed, QC thresholds, endpoints
  models.py        User / Dataset / Speaker / Script / RecordingSession / Recording / ExportBatch
  deps.py          auth dependencies (get_current_user / require_admin, token-in-query for media)
  routers/         REST API (auth, datasets, recorder, status, speakers, sessions, scripts, recordings, exports)
  services/
    auth.py             stdlib password hashing (PBKDF2) + HMAC-signed tokens
    text_normalize.py   Arabic normalization, CER/WER, digit verbalization
    llm_scripts.py      generation prompts + governance validation
    audio_qc.py         QC engine (per-take checks, room tone)
    audio_io.py         WAV I/O, resampling, loudness (no ffmpeg needed)
    asr_verify.py       Whisper client + advisory comparison
    exporter.py         dataset packaging (wavs + metadata + qc report + card)
    storage.py          file layout (swap point for object storage)
frontend/src
  auth.tsx              auth context (login / logout / current user)
  audio/recorder.ts     AudioWorklet PCM capture → float32 WAV
  pages/                Login, Recorder, Datasets, Team, Studio, Scripts, Review, Export, Settings
```

## Deliberately out of scope (v1)

Speaker diarization, multi-speaker annotation, crowd transcription, phonetic
annotation, Praat/ELAN, Label Studio as the primary tool. **Forced alignment**
is deferred to an offline post-export step (e.g. NVIDIA NeMo Forced Aligner or
Montreal Forced Aligner on `dataset/`) once the target TTS framework's needs
are known — the export format contains everything those tools require.
