# HosMonitor project instructions

## Mandatory pre-update approval workflow

- Before changing or adding any HosMonitor behavior, inspect the relevant code read-only and draft the complete proposal in `Pre-Update.md`.
- Do not edit source code, migrations, tests, `VERSION`, installers, or release artifacts while the proposal is awaiting review or approval.
- Start implementation only after the user explicitly approves the listed proposal in chat.
- Implement only approved items. Add any newly discovered scope to `Pre-Update.md` and obtain fresh approval before proceeding.
- After implementation, record test results, migration/rollback details, artifacts, and checksums in `Pre-Update.md`.
- Read-only diagnosis, explanation, and status inspection are allowed before approval, but fixes are not.
- Never expose Agent tokens, private signing keys, passwords, patient data, or other secrets in the proposal, logs, or responses.

