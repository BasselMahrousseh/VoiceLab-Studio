# Azure App Service production deployment

The `PROD` branch deploys VoiceLab Studio to the Linux App Service
`AI-Cognitive-SandBox-VoiceLab` through
`.github/workflows/deploy-prod.yml`.

## App Service

- Publish: Code
- Operating system: Linux
- Runtime: Python 3.13
- Startup command: `bash startup.sh`
- Scale: one instance while SQLite is in use
- Worker count: one (enforced by `startup.sh`)

The compiled React SPA and FastAPI API are served from the same process on the
App Service `PORT`.

## GitHub configuration

Create a GitHub environment named `production`. Configure these environment or
repository secrets for Azure OIDC:

- `AZURE_CLIENT_ID`: client ID of the identity used by GitHub Actions to deploy
- `AZURE_TENANT_ID`: `956d0a5b-65df-40ee-b210-145b0e79eac8`
- `AZURE_SUBSCRIPTION_ID`: `8133fc6d-2303-439c-b881-f8df6b912bef`

Configure this GitHub variable:

- `AZURE_MANAGED_IDENTITY_CLIENT_ID`: client ID of the user-assigned managed
  identity `AI-Cognitive-General`

The GitHub deployment identity and the App Service runtime identity may be the
same Azure identity, but separate least-privilege identities are preferable.
The deployment identity requires permission to update and deploy this Web App.
It also needs a federated credential whose subject matches the GitHub
`production` environment.

## Runtime identity and access

Attach `AI-Cognitive-General` to the App Service, then grant it:

- `Storage Blob Data Contributor` on the `voicelab` container
- `Cognitive Services OpenAI User` on
  `AICognitiveDevAISandBoxOpenAI-01`

The application uses `DefaultAzureCredential` with the configured user-assigned
identity. No Storage account key or Azure OpenAI API key is required.

## Persistent data

Application metadata is stored in `/home/data/voicelab.db`. The App Service
must stay at one instance and one Uvicorn worker while SQLite is used.

Recording masters are stored below `audio/` in the `voicelab` Blob container.
Generated exports are stored below `exports/`. An administrator can request a
consistent SQLite backup through:

```text
POST /api/exports/database-backup
```

Backups are uploaded below `database-backups/`.

Never mount the SQLite database on Blob Storage or Azure Files. Move to a
managed relational database before enabling App Service scale-out.

## Continuous deployment

Every push to `PROD` runs backend tests, frontend type checking and build, then
deploys the assembled application ZIP. Runtime data under `/home/data` and Blob
Storage is not part of the package and is not overwritten by deployment.
