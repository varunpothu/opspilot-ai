# OpsPilot AI status

This file distinguishes the code that exists in this repository from planned work.

## Implemented in this repository

- FastAPI health, create-run, list-runs, run-detail and report endpoints.
- Fixture-backed checks for pipeline status, schema drift, volume anomalies, source freshness and dashboard staleness.
- Evidence-linked deterministic signals and explicitly labelled root-cause hypotheses.
- SQLite persistence for incident run records.
- CLI entry point for local analysis.
- Sample warehouse incident fixture and basic tests.
- Read-only source handling; remediation plans are proposed only and are not executed.

## Still planned

- Migration of the complete inherited RepoSentinel engine and its original tests/artifacts.
- Integration adapters for GitHub, dbt, SQL databases, cloud services and model-serving systems.
- Authentication, user identities and approval UI.
- React dashboard, distributed job queue, production deployment and multi-tenancy.
- Executable sandbox remediation. Current MVP only emits a proposed dry-run plan.

## Important evaluation note

The inherited RepoSentinel ZIP contains separate synthetic benchmarks. They have not yet been migrated into this repository or rerun against this MVP. Do not claim their scores as OpsPilot AI results. Preserve the original artifacts and benchmark methodology during the migration.
