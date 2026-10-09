# OpsPilot AI status

Status is intentionally explicit. This repository is an early MVP, not a production incident operator.

## Implemented and committed

- FastAPI health, create-run, list-runs, run-detail and report endpoints.
- CLI for fixture-backed incident analysis and JSON export.
- Deterministic checks for pipeline status, schema drift, volume anomalies, source freshness, dashboard staleness, dashboard/source metric mismatch, null-rate spikes and pipeline duration SLO breaches.
- Evidence-linked signals with stable identifiers and SHA-256 hashes for the four input fixture files.
- Rule-based candidate hypotheses with supporting signal IDs.
- SQLite run history.
- Explicit run lifecycle state machine with fail-closed legal transitions.
- Read-only fixture connector with target/path validation, required-file allowlist and per-file size limit.
- Disposable sandbox simulation with allowlisted JSON changes, post-repair checks, zero production writes and an assertion that original fixture bytes remain unchanged.
- All ten inherited operations fixture scenarios: pipeline failure, schema drift, null spike, dashboard mismatch, freshness SLA, volume drop, multiple incidents, healthy operation, slow pipeline and dashboard-stale-only.
- Reproducible fixture benchmark CLI recording fixture SHA-256 hashes, code version and run summaries.
- Versioned fail-closed policy evaluator with severity-based risk score, review flags and blocked high-impact actions.
- Deterministic P1–P4 triage, incident fingerprints and rule-based signal correlation.
- Per-run hash-linked audit chain with verification endpoint and tamper-detection tests.
- Optional baseline-driven data contracts for required/allowed columns, row-count bounds and null-rate ceilings.
- Bounded recent-run JSON metrics summary endpoint; explicitly not an OpenTelemetry exporter or rolling SLO calculator.
- Advanced-mechanisms research roadmap covering OWASP, OPA, OpenTelemetry, SLSA and NIST AI RMF.
- Scheduled CodeQL security analysis workflow (workflow committed; scan result depends on GitHub Actions execution).\n- CI across Python 3.11 and 3.12, including benchmark artifact generation and upload.

## Not yet migrated from RepoSentinel.zip

The complete original source tree, all 16 operations agents, repository-analysis agents, legacy CLI entry points, original test suite, full set of 10 operations fixtures, 24-case repository-analysis examples, saved benchmark outputs, SARIF examples, reports and original documentation are not yet present as native files in this repository. The current five fixtures are a partial migration of the operations scenarios, not a replacement for the original archive.

The original benchmark results have not been rerun against this MVP and must not be presented as OpsPilot AI performance.

## Not implemented

- Execution of the original 16-agent OpsWorkflow through the new run service.
- Real GitHub, dbt, SQL warehouse, AWS, monitoring or model-serving connectors.
- LLM-based reasoning in the new MVP package.
- Production repair, shell execution, public deployment, authentication, multi-tenancy or approval UI.
- React dashboard, queue workers, PostgreSQL or cloud deployment.
- External OPA service, OpenTelemetry exporter, signed SLSA attestations, immutable external audit sink or production-grade identity/role authorisation.

## Release gates still outstanding

- Migrate and preserve the complete RepoSentinel source tree, tests, artifacts and documentation.
- Run legacy tests, self-check and benchmark against the preserved engine.
- Adapt the original OpsWorkflow through an adapter and test agent failures as failed/partial runs.
- Complete security, regression and idempotency tests.
- Publish a versioned evaluation manifest and a reproducible local demo.

Do not tag the full product as complete or production-ready until these gates pass.
