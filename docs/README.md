# e& Lahja Studio — Documentation

Technical documentation for **e& Lahja Studio**, the Emirati voice-recording and
dataset-quality platform for building TTS / voice-cloning training data.

| Document | What it covers |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System overview, components, request flows, audio pipeline, security, diagrams |
| [TECH_STACK.md](TECH_STACK.md) | Every technology used, versions, and why |
| [DATA_AND_STORAGE.md](DATA_AND_STORAGE.md) | Where data is saved, the database, full schema, file layout, backups, migrations |
| [AZURE_APP_SERVICE.md](AZURE_APP_SERVICE.md) | PROD GitHub Actions deployment, Managed Identity, Blob Storage, persistent SQLite |

See also the repo root [README.md](../README.md) (quick start & workflow),
[POLICY.md](../POLICY.md) (Arabic/Emirati text policy), and
[.env.example](../.env.example) (configuration).

## 30-second summary

- **One process, one port.** A FastAPI (Python) backend serves the REST API
  under `/api` and the built React SPA at `/` on `http://127.0.0.1:8000`.
- **Storage.** A SQL database (SQLite by default) holds all metadata; audio WAV
  masters and exports live on disk under `data/`.
- **Roles.** Admins (data scientists) plan datasets — including with GenAI
  (GPT-5.6-sol) — and manage recorders; recorders log in and read scripts aloud.
- **Audio.** The browser captures lossless Float32 PCM; the server runs quality
  checks, stores masters untouched, and derives PCM-16 exports on demand.
