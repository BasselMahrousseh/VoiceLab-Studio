# VoiceLab product reevaluation

## Purpose

VoiceLab Studio is a controlled data-production workflow for collecting
model-ready speech pairs:

`dataset plan → governed scripts → assigned voice talent → lossless recording
→ automated QC / advisory ASR → human review → reproducible dataset export`

The primary object is the **dataset**. Scripts, recorder assignments, recording
instructions, language rules, policy additions, progress, reviews, and exports
must retain dataset ownership.

## Page responsibilities

| Page | Responsibility | Must not become |
|---|---|---|
| Datasets | Create and manage the work unit: languages, policy, scripts, people, targets and progress | A passive folder list |
| Team | Accounts, credentials, active state, voice identity and current dataset assignment | Script management |
| Studio | Admin-assisted recording for one selected dataset and speaker session | A global cross-project queue |
| Script library | Cross-dataset search, QA, metadata correction and retirement | A second dataset-creation workflow |
| Review | Dataset-filterable audio/QC/ASR/human decision queue | An unscoped recording dump |
| Export | Reproducible export of one selected dataset with policy and per-sentence metadata | A mixture of unrelated projects |
| Settings | Service health and editable global governance defaults | Dataset-specific configuration |

## Corrections implemented in v0.2

- The global text policy is database-backed and editable in Settings.
- Dataset creation shows the global policy and accepts dataset-specific
  additions. Both are supplied to GenAI generation.
- Datasets declare one or more allowed language tags: `ar-AE`, `en-US`,
  `mixed`.
- Every script stores and exports its own language, dialect and
  `language:<tag>` metadata tag. Auto-detection is available for pasted lines.
- Dataset language constraints are enforced when scripts are imported.
- The Script tab is now a library/editor; generation and import live under the
  owning dataset.
- Studio, Review and Export can be scoped to a dataset.
- ASR uses Arabic for `ar-AE`, English for `en-US`, and language auto-detection
  for `mixed`.
- Exports include the effective text policy and preserve one accepted take per
  script **per speaker**, avoiding accidental loss of other voices.

## Recommended next priorities

### Production governance

1. Add policy revision history and store a frozen policy revision on every
   generated batch and export.
2. Add immutable audit events for script edits, transcript edits, review
   decisions, assignments and policy changes.
3. Add speaker consent / usage-rights metadata and retention controls before
   collecting production voices.

### Dataset quality

1. Add per-dataset coverage dashboards for language, dialect, style, domain,
   duration, speaker and lexical/phonetic coverage.
2. Add train/validation/test split generation with speaker-safe split rules.
3. Add configurable acceptance gates per dataset instead of only application
   wide QC thresholds.

### Scale and reliability

1. Move long GenAI generation and large exports to durable background jobs with
   resumable progress. The current live stream is appropriate for a pilot but
   an App Service restart ends an in-flight request.
2. Add a many-to-many recorder assignment/work-queue model only if a recorder
   must work on multiple active datasets concurrently. The current model
   intentionally gives each recorder one active dataset.
3. Add formal database migrations (Alembic) before moving from the current
   single-instance SQLite deployment to a managed SQL service.

With the v0.2 corrections, the application is coherent for a controlled pilot.
The governance, auditability, and durable-job items above are the main boundary
between a pilot tool and a production corpus operation.
