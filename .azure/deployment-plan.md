# VoiceLab Studio Azure Deployment Plan

## Status

Application validated — Azure resource/RBAC preflight pending

## Scope

- Modernize and deploy the existing FastAPI + React application to Azure App Service.
- Reuse the supplied user-assigned managed identity and Blob Storage container.
- Connect the application to a managed SQL database.
- Configure the selected Azure OpenAI model deployments.
- Deploy application releases through GitHub Actions.

## Confirmed existing resources

- Subscription: `8133fc6d-2303-439c-b881-f8df6b912bef`
- Resource group: `CIT-AI-Cognitive-Dev-AISandBox-RG-01`
- User-assigned managed identity: `AI-Cognitive-General`
- Storage account: `aicognitivesandboxstrg`
- Blob container: `voicelab`
- Azure OpenAI account: `AICognitiveDevAISandBoxOpenAI-01`
- Script model deployment: `gpt-5.6-sol`
- File transcription deployment: `gpt-4o-transcribe`
- Realtime transcription deployment: `gpt-realtime-whisper` (reserved for a future realtime path)

## Proposed architecture

- Azure App Service hosts one production process: FastAPI serving `/api` and the compiled React SPA.
- Azure Blob Storage stores recording masters and generated export artifacts.
- For the initial single-instance sandbox deployment, SQLite stores application
  metadata under App Service persistent storage at `/home/data/voicelab.db`.
- A managed SQL database remains the production scale-out migration target.
- `AI-Cognitive-General` authenticates the App Service to Blob Storage, Azure OpenAI, and the database where supported.
- App Service application settings hold non-secret configuration; Key Vault references hold unavoidable secrets.

## Planned application changes

- Replace filesystem-only recording storage with a Blob-capable storage interface.
- Preserve local filesystem storage for development and tests.
- Stage export work in temporary storage, upload completed artifacts to Blob Storage, and stream downloads from Blob.
- Add Azure Identity and Blob Storage SDK dependencies.
- Add settings for storage backend, account URL, container, and user-assigned identity client ID.
- Configure the production container to run only Uvicorn on port 8000.
- Add database driver and Alembic migrations after the SQL engine is confirmed.
- Document Azure configuration, role assignments, deployment, and recovery.
- Add a GitHub Actions workflow that builds the React SPA, tests the backend,
  packages the application, and deploys it to App Service using OIDC.
- Set `DATA_DIR=/home/data` and add a safe SQLite backup procedure that uses
  SQLite's backup API and uploads completed backups to Blob Storage.

## Required access

- Assign `AI-Cognitive-General` to the App Service.
- Grant `Storage Blob Data Contributor` scoped to the `voicelab` container.
- Grant the identity the appropriate Azure OpenAI inference role on `AICognitiveDevAISandBoxOpenAI-01`.
- Grant least-privilege database access after the SQL engine and database resource are confirmed.
- Grant Key Vault secret-read access only if API-key authentication remains necessary.

## Proposed application settings

```text
STORAGE_BACKEND=azure_blob
AZURE_STORAGE_ACCOUNT_URL=https://aicognitivesandboxstrg.blob.core.windows.net
AZURE_STORAGE_CONTAINER=voicelab
AZURE_CLIENT_ID=<AI-Cognitive-General client ID>

LLM_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://AICognitiveDevAISandBoxOpenAI-01.openai.azure.com/
LLM_DEPLOYMENT=gpt-5.6-sol
LLM_API_STYLE=responses

ASR_PROVIDER=azure
ASR_DEPLOYMENT=gpt-4o-transcribe
ASR_LANGUAGE=ar

REALTIME_ASR_DEPLOYMENT=gpt-realtime-whisper

DATA_DIR=/home/data
```

`DATABASE_URL` remains unset for the initial SQLite deployment. SQLite is an
interim single-instance choice and must not be placed on a Blob/Azure Files
mount.

## Deployment decisions

- Proposed App Service name: `AI-Cognitive-SandBox-VoiceLab`.
- Proposed App Service configuration: Code publish, Linux, Python 3.13, one
  instance, one Uvicorn worker. B1 is acceptable for a sandbox; P0v3 is
  preferred for a production workload.
- Future database choice: Azure SQL Database requires a deliberate driver and
  Entra-token integration; Cosmos DB or Table Storage requires a larger data
  access rewrite.
- Existing resources are configured through App Service settings in the GitHub
  Actions workflow; this branch does not provision resources through IaC.
- Storage and Azure OpenAI network reachability must be confirmed in the target
  Azure environment before the first deployment.
- Realtime transcription is reserved in configuration; the initial release
  continues to use completed-file transcription.

## Validation

- Unit and API tests pass with local storage.
- Blob integration tests cover upload, playback, ASR download, export upload, and export download.
- Database migrations apply to a clean and an upgraded database.
- Production container serves the SPA and API on port 8000.
- Managed Identity authentication succeeds without storage or database secrets.
- End-to-end flow passes: login, record, QC, accept, transcribe, export, download.
- SQLite data survives App Service restart and GitHub Actions redeployment.
- Restore from a Blob-hosted SQLite backup succeeds.

### Validation proof

- `python -m pytest backend/tests -q`: 12 passed.
- `npm run typecheck`: passed.
- `npm run build`: passed; production SPA emitted to `frontend/dist`.
- `npm audit --omit=dev`: no high or critical production dependency advisory
  remains; two moderate React Router advisories affect redirect/SSR behavior
  not used by this client-only SPA and currently have no non-conflicting
  patched release line.
- Workflow YAML parsed successfully.
- Production TestClient smoke check served the compiled SPA through FastAPI.
- Blob adapter unit tests cover master upload/read, export upload/stream, and
  consistent SQLite backup upload.

### Role assignment verification

- Runtime identity: `AI-Cognitive-General`.
- Required storage role: `Storage Blob Data Contributor`, scoped to the
  `voicelab` container.
- Required model role: `Cognitive Services OpenAI User`, scoped to
  `AICognitiveDevAISandBoxOpenAI-01`.
- GitHub OIDC deployment identity requires least-privilege Web App deployment
  and configuration rights on `AI-Cognitive-SandBox-VoiceLab`.
- Static application configuration is complete. Live role assignments, the
  user-assigned identity client ID, federated credential, App Service existence,
  and network access cannot be validated until those Azure/GitHub settings are
  created.

## Execution gate

Implementation was approved by the request to create the `PROD` branch.
Deployment remains user-controlled through GitHub Actions.
