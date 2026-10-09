# RepoSentinel to OpsPilot AI migration record

## Source archive provenance

- Source filename supplied in the conversation: `RepoSentinel.zip`
- SHA-256: `5aa68d2e28837ac61a1accf190eaaa0dd84d73673159919951cac5a94d4afc4d`
- Archive inventory: 283 files (directories excluded)
- Legacy operations fixtures: 10 case directories
- Legacy repository-analysis benchmark artifacts: 24 baseline JSON files and 24 advanced JSON files
- Legacy source package: `src/reposentinel/`, including repository-analysis agents and a 16-agent operations workflow

The source archive is the provenance reference for this migration. The original benchmark files must remain unchanged and separate from new OpsPilot AI measurements.

## Migration principle

OpsPilot AI is the public product name. The legacy `reposentinel` Python import path and CLI behavior should remain available while the existing engine is integrated. Do not rewrite the legacy engine as part of the package rename. The recommended integration is an adapter around the existing `OpsWorkflow`, not a second implementation of its agents.

## Present in the OpsPilot AI repository

- A new `opspilot_ai` MVP package with FastAPI, CLI, typed contracts and SQLite run history.
- A fixture connector with a strict four-file allowlist, path checks, file size limits and SHA-256 evidence hashes.
- Deterministic checks for pipeline state, schema, row volume, source freshness, dashboard freshness and metric consistency, null-rate spikes and pipeline SLO breaches.
- A lifecycle state machine.
- A disposable sandbox simulator that only edits copied JSON fixtures and checks its own postconditions.
- Five migrated operations fixture cases: `01_pipeline_failure_stale_dashboard`, `02_schema_drift`, `03_null_spike`, `06_volume_drop`, and `08_healthy`.
- API, lifecycle, connector and sandbox tests, plus CI on Python 3.11 and 3.12.

## Not yet migrated

The following remain outstanding and are not implied by the current MVP:

1. The full `src/reposentinel/` package and its 16 operations agents.
2. The repository-analysis agent suite and original CLI entry points.
3. The remaining five operations fixture cases.
4. All 24 repository-analysis examples, original tests, self-check and benchmark runner.
5. Historical `artifacts/case_*`, SARIF, report, evaluation, email and operations console artifacts.
6. The original agent prompt/contract documents and full architecture/security documentation.
7. The adapter that runs the original `OpsWorkflow` inside the new run lifecycle.
8. A regression report comparing the untouched original benchmark to the same evaluator after integration.

## Next implementation sequence

1. Copy the complete legacy source, tests, examples, schemas, reports, prompts, documentation and benchmark artifacts into the repository without altering historical outputs.
2. Inspect and retain the original license and contributor attribution. Do not silently relicense inherited code.
3. Make the original clean install, test suite, self-check, operations benchmark and 24-case evaluator reproducible.
4. Add a `LegacyOpsWorkflowAdapter` that calls the existing workflow on an allowlisted fixture directory and maps its signals, root causes, actions, validation and trajectory into the versioned OpsPilot contract.
5. Fail or mark a run partial when any critical agent raises an exception. Never convert a failed validation into a successful run.
6. Add regression tests proving the old CLI/imports still work and that sandbox changes never alter original fixture bytes.
7. Store new evaluation outputs separately, with archive SHA, code commit, Python version, fixture hashes and evaluator version.
8. Only then consider a `0.1.0` release.

## Safety boundary

The current sandbox is a fixture simulation. It is not a warehouse repair, pipeline retry against a real scheduler, or production connector. It does not execute commands, contact cloud systems, or write to production. The legacy engine's own sandbox should also be reviewed and tested before it is exposed through the API.

## Completion criteria

Call the migration complete only when all inherited source files and historical artifacts are preserved, the legacy regression suite and self-check pass, the original operations workflow runs through the adapter, API and CLI behavior are covered by tests, sandbox invariants pass, and the evaluation outputs are reproducible. Until then, describe the repository as an MVP with a partial legacy fixture migration.
