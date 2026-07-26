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

The Azure portal created the repository secrets used by the workflow:

- `AZUREAPPSERVICE_CLIENTID_C8B149B4708B4B48A8AF823C22264C97`
- `AZUREAPPSERVICE_TENANTID_18201DE120B044889389130FE024BC74`
- `AZUREAPPSERVICE_SUBSCRIPTIONID_B949D3BC6DCA4646BD06F2206414232B`

The runtime client ID for `AI-Cognitive-General` is non-secret and is configured
directly as the App Service `AZURE_CLIENT_ID` setting.

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
