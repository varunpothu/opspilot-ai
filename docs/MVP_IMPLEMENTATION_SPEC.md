# OpsPilot AI
## MVP Implementation Specification

**Product title:** OpsPilot AI: Evidence-Driven Data and AI Operations  
**Repository:** `opspilot-ai`  
**Development strategy:** Working MVP first. Preserve the existing RepoSentinel implementation and benchmark artifacts.

## 1. Product vision

OpsPilot AI helps data and AI engineering teams investigate data pipeline and AI workload incidents. It gathers configured signals, correlates evidence, proposes likely causes, plans safe remediation, validates results in an isolated environment, and records the outcome.

The MVP is a local-first, evidence-driven incident investigation product. It is not an unrestricted autonomous production operator.

### MVP goals

- Detect selected data reliability conditions from fixture inputs.
- Explain each finding with evidence and thresholds.
- Distinguish raw observations, deterministic detections, and AI-generated hypotheses.
- Generate remediation plans and execute only named actions in a disposable local sandbox.
- Validate post-action invariants and prevent false success when validation fails.
- Persist incident runs and export reports.
- Expose a small REST API and product-facing CLI.
- Preserve the existing deterministic CLI and benchmark throughout migration.

### Non-goals

- No autonomous production writes.
- No arbitrary shell command execution.
- No multi-tenant service, enterprise SSO, or public unauthenticated API.
- No mandatory paid LLM or cloud account.
- No claim that synthetic benchmark scores represent general production accuracy.
- No claim of real GitHub, AWS, dbt, Slack, or model-serving integration until implemented and tested.

## 2. Existing codebase: migration assumptions

The supplied RepoSentinel archive is a Python 3.11+ project with code under `src/reposentinel/`. The documented operations workflow is fixture-driven, uses structured signals and staged agents, modifies copied JSON fixture state in a sandbox, and emits local report artifacts. Repository-analysis and operations benchmark artifacts are synthetic and should remain unchanged.

Preserve these distinctions in the README and UI:
- **Implemented:** verified by code and tests.
- **Fixture/demo:** works only against sample or local fixture data.
- **Planned:** design only, not implemented.
- **Not supported:** explicitly outside current scope.

Do not rewrite the agent engine as part of the initial rename. Keep `src/reposentinel/` as the import path until compatibility tests exist. Add a product-facing `opspilot` command as an alias only after verifying the existing entry point.

## 3. MVP acceptance criteria

1. Existing tests, CLI commands, self-checks and benchmark scripts continue to work.
2. Each run has a UUID, schema version, timestamps and a documented lifecycle state.
3. Fixture inputs are validated before analysis and cannot escape the configured fixture root.
4. Signals expose stable IDs, severity, observed/expected values, evidence references, detector name/version and timestamp.
5. Hypotheses link to supporting and contradicting evidence where available and are not presented as facts.
6. API inputs use validated typed schemas; unsupported connectors and production-write modes are rejected.
7. Run details remain inspectable after process restart.
8. Sandbox remediation touches copies only, runs named actions only, and is validated afterwards.
9. Validation failure prevents an action or run from being marked successful.
10. Reports are served only from an artifact registry, never from arbitrary caller-supplied paths.
11. CI runs unit, integration, security and regression tests.
12. Existing benchmark files and historical scores are preserved verbatim.

## 4. Architecture

```text
CLI / FastAPI
     |
Run Service and Lifecycle
     |
Connector Interface ---- Fixture Connector (MVP)
     |
Existing OpsWorkflow and deterministic agents
     |
Evidence + Finding Normalizer
     |
Hypothesis Correlator
     |
Policy Gate ---- Read-only / Dry-run / Sandbox only
     |
Sandbox Repair + Validator
     |
Run Repository (SQLite)
     |
JSON / HTML / Text Report Artifacts
```

Keep the existing workflow as the analysis engine. Add adapters around it instead of rewriting the specialist agents. Run synchronously in-process for the first MVP; do not add Redis/Celery until a demonstrated asynchronous workload requires it.

## 5. Target repository structure

This is a target layout. Add folders as implementation starts; do not create empty scaffolding only for appearance.

```text
opspilot-ai/
├── src/reposentinel/          # Existing engine retained during migration
│   ├── api/                   # FastAPI routes, added incrementally
│   ├── application/           # Run service, lifecycle, contracts
│   ├── connectors/            # Connector protocol and fixture connector
│   ├── persistence/           # SQLite repository and migrations
│   ├── security/              # Path policy, action policy, redaction
│   ├── ops/                   # Existing operations workflow
│   └── observability/         # Structured logging and traces
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── security/
│   └── evaluation/
├── examples/
├── docs/
│   ├── architecture/
│   ├── decisions/
│   ├── security/
│   └── runbooks/
├── scripts/
├── .github/workflows/
├── pyproject.toml
├── README.md
├── CONTRIBUTING.md
├── SECURITY.md
└── LICENSE
```

Add `apps/web/` with React/TypeScript only after API contracts stabilize.

## 6. Dependencies

Keep existing standard-library core and dependencies. Add only what the MVP needs:

- `fastapi` for REST endpoints.
- `uvicorn[standard]` for the local ASGI server.
- `pydantic` for input/output contracts.
- `sqlalchemy` for persistence abstraction.
- `alembic` for migrations when the schema stabilizes.
- `httpx` for API tests.
- `pytest-cov` for coverage.
- `ruff` for linting/formatting.
- `mypy` for optional static typing checks.

Pin tested dependency versions in project metadata and lock the environment. PostgreSQL (`psycopg`), OpenTelemetry, AI provider SDKs, Redis, Celery, vector databases and cloud SDKs are later additions only when justified.

## 7. REST API contracts

Base path: `/api/v1`.

### `GET /health`

Returns service status and API version without exposing secrets or machine details.

```json
{"status":"ok","service":"opspilot-ai","api_version":"v1"}
```

### `POST /runs`

Starts fixture-backed analysis.

```json
{
  "target": "demo-warehouse-incident",
  "mode": "analyze",
  "connector": "fixture",
  "remediation_mode": "dry_run"
}
```

Allowed MVP values: `mode=analyze`, `connector=fixture`, `remediation_mode=read_only|dry_run|sandbox`. Reject unknown connector types and all production-write modes. Choose either synchronous `201 Created` or asynchronous `202 Accepted` behavior and document it consistently. If asynchronous, return a UUID and link to the run.

### `GET /runs/{run_id}`

Returns state, timestamps, summary, redacted errors and registered artifact references.

### `GET /runs`

Bounded pagination: default `limit=20`, maximum `100`, optional cursor and status filter.

### `GET /runs/{run_id}/report`

Returns report summary and artifact metadata. Only serve artifacts indexed by the application, never arbitrary file paths.

### `POST /runs/{run_id}/cancel`

Cancels queued runs. If an already running synchronous job cannot safely be interrupted, return a documented conflict response.

### Error envelope

```json
{
  "error": {
    "code": "INVALID_CONNECTOR",
    "message": "Connector is not enabled for this deployment.",
    "request_id": "UUID"
  }
}
```

Use 400 for malformed payloads, 404 for unknown runs, 409 for invalid lifecycle transitions, 422 for schema validation, and 500 for unexpected failures. Never expose stack traces to clients.

## 8. Database schema

Use SQLite for local MVP through a repository abstraction. Keep indexed lifecycle fields relational and flexible agent details as JSON/text snapshots.

### `runs`

- `id` UUID/text primary key
- `target`, `connector_type`, `mode`, `status` required text
- `schema_version` integer required
- `created_at` required; `started_at`, `finished_at`, `duration_ms` nullable
- `summary_json` nullable
- `error_code`, `error_message_redacted` nullable
- Indexes on `(created_at)` and `(status, created_at)`

### `signals`

- `id` primary key; `run_id` foreign key
- `signal_type`, `severity`, `title` required
- `metric_name`, `observed_value_json`, `expected_value_json` optional
- `confidence` nullable, constrained to 0..1
- `detector_name`, `detector_version`, `evidence_json`, `created_at` required
- Index `(run_id, severity)`

### `hypotheses`

- `id` primary key; `run_id` foreign key
- `title`, `description` required
- `confidence` nullable
- `status`: `candidate`, `supported`, `rejected`, `unresolved`
- Supporting and contradicting evidence JSON, timestamp

### `actions`

- `id` primary key; `run_id` foreign key
- `action_type`, `description`, `risk_level` required
- `mode`: `read_only`, `dry_run`, `sandbox`
- `requires_approval` boolean
- `status`: `proposed`, `rejected`, `running`, `succeeded`, `failed`, `blocked`
- optional `idempotency_key`; input/result JSON; created/finished timestamps

### `validations`

- `id` primary key; `run_id` foreign key; optional `action_id` foreign key
- `check_name` required
- `status`: `passed`, `failed`, `skipped`, `error`
- expected/actual JSON, evidence JSON, timestamp

### `events`

- auto-increment `id`; `run_id` foreign key; `sequence_no`
- `event_type`, `actor`, redacted payload JSON, timestamp
- Unique `(run_id, sequence_no)`
- Append-only at application level; never store raw secrets or unnecessary sensitive payloads.

### `artifacts`

- `id` primary key; `run_id` foreign key
- `artifact_type`, `relative_path`, `sha256`, `content_type`, `created_at`
- Caller must not set arbitrary absolute paths.

## 9. Security requirements

1. Fixture-only connector in MVP; future connectors begin read-only.
2. No production mutation endpoint or credential in MVP.
3. Use disposable sandbox directories, explicit file allowlists, size/time limits and cleanup.
4. Resolve paths and reject traversal and symlink escapes.
5. Never execute arbitrary commands supplied by a user or generated by an LLM.
6. Keep `.env` untracked; provide `.env.example` placeholders; redact secrets from events and reports.
7. Validate payloads and enums; bound request size, JSON size/depth and pagination.
8. Bind to `127.0.0.1` by default. Do not expose an unauthenticated API publicly.
9. Treat source code, logs, runbooks and upstream content as untrusted data, not privileged instructions.
10. Future write actions require authenticated approver identity, explicit diff/target, expiry, idempotency and audit record.
11. Missing evidence or failed policy/validation must stop safely.
12. Document local data retention and provide a cleanup command.
13. Add dependency and secret scanning to CI.
14. Add `docs/security/threat-model.md` covering assets, boundaries, abuse cases and controls.

## 10. Testing strategy

### Unit tests
- Contract and enum validation; lifecycle transitions.
- Stable signal IDs/fingerprints and evidence integrity.
- Confidence bounds and severity mapping.
- Path traversal, symlink escape, size limits and secret redaction.
- Policy rejection for unsupported connectors/actions.

### Integration tests
- Fixture connector loads valid JSON and rejects missing/malformed files.
- Existing `OpsWorkflow` works through adapter without behavior regression.
- Runs/signals/events/artifacts persist in SQLite.
- API can create and retrieve a run.
- Report endpoint serves only registered artifacts.
- Sandbox repair leaves source fixtures byte-identical.
- Validation failure blocks successful remediation/run status.
- Critical agent failure is recorded and cannot silently pass.

### Regression tests
- Keep existing repository-analysis tests and self-check.
- Preserve historical synthetic 24-case repository-analysis baseline/advanced results and artifacts.
- Add versioned ops fixtures: healthy, stale data, schema drift, volume anomaly, pipeline failure and failed repair validation.
- Compare baseline and candidate on the same fixtures.
- Publish precision/recall/F1 only where independent ground truth exists. Measure latency and errors separately.
- Do not tune on held-out test cases.

### Security tests
- `../` and encoded traversal, symlink escapes, oversized JSON, malformed input.
- Unknown connector/action types and arbitrary command injection attempts.
- Secret leakage in API errors, events and reports.
- Artifact path tampering and duplicate requests.

### MVP release gates
- Existing tests and self-check pass.
- New API/integration/security tests pass.
- Source fixtures remain byte-identical after sandbox actions.
- Every finding has evidence or is labelled unverified.
- Failed validation never yields success.
- No production write path exists.
- Clean install succeeds with documented commands.

## 11. Rename and migration plan

1. Create `opspilot-ai` and preserve an untouched copy of the source archive.
2. Inspect licence, `.gitignore`, credentials and generated files before public push.
3. Update README, docs and user-facing branding to OpsPilot AI; document RepoSentinel as the inherited engine name during transition.
4. Retain the `src/reposentinel/` import path for the first MVP phases.
5. Add an `opspilot` CLI alias only with compatibility tests; keep legacy commands operational.
6. Change package metadata only after tests exist. Distribution name and Python import name are distinct.
7. Preserve benchmarks verbatim; add a new benchmark manifest with fixture hashes, evaluator version and timestamp.
8. Add migration tests for CLI output paths, artifact formats and imports.
9. Remove duplicate/generated artifacts only after their purpose is understood and regeneration is verified.
10. Tag `0.1.0` only after the release gates pass. Do not describe fixture-tested functionality as production-ready.

If the supplied archive has no Git history, start a clean repository and document archive provenance. Do not claim commit history has been preserved.

## 12. Implementation phases

### Phase 0: baseline and repo hygiene
- Save an untouched source copy.
- Run clean install, tests, self-check and benchmarks.
- Record Python version, commands, exit codes and artifact hashes.
- Review license, ignore rules, secrets and generated files.
- Add `BASELINE.md` documenting current functionality and limitations.

**Exit condition:** existing behavior and benchmark artifacts are reproducible.

### Phase 1: product rename
- Update README title, tagline, capability matrix, package description and CI names.
- Add product-facing CLI alias behind tests.
- Verify old/new commands produce equivalent results.

**Exit condition:** legacy and new entry points both work.

### Phase 2: contracts and lifecycle
- Implement Pydantic models, lifecycle states, run IDs and schema versioning.
- Add a run service wrapping the existing `OpsWorkflow`.
- Normalize safe errors and record failed steps.

**Exit condition:** validated run contract works independently of CLI/API.

### Phase 3: persistence
- Implement SQLAlchemy models, repositories and migration.
- Persist run summary, signals, hypotheses, actions, validations, events and artifact metadata.
- Test persistence and secret redaction.

**Exit condition:** completed runs remain inspectable after restart.

### Phase 4: fixture connector and evidence
- Define connector protocol and fixture-only implementation.
- Validate filenames, JSON schema and root directory.
- Hash source files and attach provenance.
- Normalize existing signals into stable contracts.

**Exit condition:** same fixture produces reproducible evidence.

### Phase 5: REST API
- Implement health, create/list/get run and report endpoints.
- Add bounded pagination, request IDs and consistent errors.
- Bind localhost by default; test with `httpx`.

**Exit condition:** a user can start and inspect fixture-backed analysis over HTTP.

### Phase 6: policy and sandbox
- Make read-only the default.
- Separate plan generation from execution.
- Permit named sandbox actions only.
- Enforce path allowlists, resource limits and cleanup.
- Validate post-action invariants and block success when checks fail.

**Exit condition:** source fixtures stay unchanged and unsafe actions are rejected.

### Phase 7: user experience and real integrations
- Improve existing HTML report with timeline, evidence and validation.
- Stabilize API before adding React frontend.
- Add first real integration as read-only GitHub or dbt artifacts/SQL.
- Add an AI provider behind a feature flag with deterministic fallback.
- Add tracing/cost metrics after interfaces settle.

**Exit condition:** demonstrate a real read-only integration and end-to-end incident investigation.

### Phase 8: release
- Publish architecture diagram, threat model, API examples and local setup.
- Record demo from detection to verified sandbox outcome.
- Publish evaluation method and limitations.
- Add contribution instructions and release checks.

**Exit condition:** clean reproducible MVP passes all release gates.

## 13. Proposed README

# OpsPilot AI
**Evidence-driven data and AI operations**

OpsPilot AI is a local-first engineering operations platform for investigating data pipeline and AI workload incidents. It brings deterministic reliability checks, structured evidence, root-cause hypotheses, safe sandbox remediation and post-action validation into an auditable workflow.

### Inherited capabilities (verify with tests before release)
- Deterministic repository-analysis agents.
- Fixture-driven checks for freshness, schema, volume, distribution, pipeline and dashboard signals.
- Sequential operations workflow with structured signals and trajectory records.
- Sandbox repair of copied JSON fixtures and validation.
- JSON/HTML/text incident artifacts and optional SMTP delivery.
- Synthetic evaluation fixtures and regression tests.

### MVP targets
- Typed REST API and durable run history.
- SQLite persistence.
- Versioned evidence/incident contracts.
- Stronger failure semantics and security tests.
- Product-facing CLI alias.
- Read-only integration adapters.
- Improved incident dashboard.

### Safety
The MVP is read-only by default. Remediation is simulated or sandboxed. Production changes are out of scope. Findings and root-cause hypotheses must be reviewed against evidence.

### Evaluation
Included benchmark artifacts use synthetic deterministic fixtures. Their scores describe performance on that suite only, not general production accuracy.

## 14. Definition of done

- Clean install works with documented steps.
- Existing repository and operations workflows pass regression tests.
- CLI and API can start fixture-backed runs.
- Runs persist and can be retrieved after restart.
- Signals include evidence and provenance.
- Hypotheses are explicitly labelled as hypotheses.
- Actions are read-only, dry-run or sandbox only.
- Validation failure blocks success.
- Original fixtures remain unchanged.
- API, integration and security tests pass in CI.
- README distinguishes implemented features, fixtures and future integrations.
- Historical benchmark artifacts remain preserved and new evaluations are reproducible.

**Immediate next step:** complete Phase 0 only. Do not add frontend, cloud deployment, an LLM framework and multiple external integrations before the baseline and core contracts are stable.
