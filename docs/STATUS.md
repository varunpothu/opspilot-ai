# OpsPilot AI status

Status is intentionally explicit. This repository is an early MVP, not a production incident operator.

## Implemented and committed

- FastAPI health, create-run, list-runs, run-detail and report endpoints.
- CLI for fixture-backed incident analysis and JSON export.
- Deterministic checks for pipeline status, schema drift, volume anomalies, source freshness, dashboard staleness, dashboard/source metric mismatch, null-rate spikes and pipeline duration SLO breaches.
- Evidence-linked signals with stable identifiers and SHA-256 hashes for the four input fixture files.
- Rule-based candidate hypotheses with supporting signal IDs.
- SQLite run history and an explicit run lifecycle state machine.
- Read-only fixture connector with target/path validation, required-file allowlist and per-file size limit.
- Disposable sandbox simulation with allowlisted JSON changes, post-repair checks, zero production writes and an assertion that original fixture bytes remain unchanged.
- Ten inherited operations fixture scenarios: pipeline failure, schema drift, null spike, dashboard mismatch, freshness SLA, volume drop, multiple incidents, healthy operation, slow pipeline and dashboard-stale-only.
- Reproducible fixture benchmark CLI and CI across Python 3.11 and 3.12.
- Versioned fail-closed policy evaluator, risk scoring, human-review flags and blocked high-impact actions.
- Deterministic P1-P4 triage, incident fingerprints and rule-based signal correlation.
- Per-run hash-linked audit chain with verification endpoint and tamper-detection tests.
- Optional baseline-driven data contracts for required/allowed columns, row-count bounds and null-rate ceilings.
- Bounded recent-run JSON metrics summary; not an OpenTelemetry exporter or rolling SLO calculator.
- Bearer-token authentication with viewer/operator/approver/admin roles. Authentication is required by default except for the health endpoint.
- Human approval workflow with a 30-minute expiry, separate requester/approver identity, reason capture and hash-linked decision events. Approval never executes remediation.
- Actor-scoped SQLite idempotency for API run creation; matching repeats replay the original response.
- Bounded retry/backoff, process-local retry budget and closed/open/half-open circuit-breaker primitives. No production connector uses these primitives yet.
- Research roadmap, security/threat-model documentation and scheduled CodeQL security analysis.

## Not yet migrated from RepoSentinel.zip

The complete original source tree, all 16 operations agents, repository-analysis agents, legacy CLI entry points, original test suite, all inherited operations fixtures, 24-case repository-analysis examples, saved benchmark outputs, SARIF examples, reports and original documentation are not yet present as native files in this repository. The current ten operations fixtures are a partial migration of the archive, not a replacement for the original source tree.

The original benchmark results have not been rerun against this MVP and must not be presented as OpsPilot AI performance.

## Not implemented

- Execution of the original 16-agent OpsWorkflow through the new run service.
- Real GitHub, dbt, SQL warehouse, AWS, monitoring or model-serving connectors.
- LLM-based reasoning in the new MVP package.
- Production repair, shell execution or autonomous actions.
- External identity-provider integration, token lifecycle/rotation, multi-tenant isolation, public deployment or a React dashboard.
- External OPA service, OpenTelemetry exporter, signed SLSA attestations or external immutable audit sink.
- Distributed retry budgets, distributed idempotency or a persistent queue.

## Release gates still outstanding

- Migrate and preserve the complete RepoSentinel source tree, tests, artifacts and documentation.
- Run legacy tests, self-check and benchmark against the preserved engine.
- Adapt the original OpsWorkflow through an adapter and test agent failures as failed/partial runs.
- Complete an independent security review, external connector regression tests and production idempotency/concurrency review.
- Publish a versioned evaluation manifest and a reproducible local demo.

Do not tag the full product as complete or production-ready until these gates pass.
