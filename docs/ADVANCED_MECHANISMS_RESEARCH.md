# OpsPilot AI: advanced mechanisms research and implementation plan

**Research updated:** 9 October 2026  
**Scope:** Local-first Data and AI operations MVP. Recommendations distinguish code implemented in this branch from integration work that remains planned.

## Research-backed design principles

1. **Agentic AI safety and least agency.** OWASP's 2026 Agentic Applications guidance and its Excessive Agency guidance emphasize limiting tool functionality, permissions and autonomy; high-impact actions need independent verification and approval. OpsPilot should keep analysis separate from action execution and default-deny every mutation. Sources: [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/), [OWASP Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/).
2. **Policy as code.** OPA separates policy decision-making from enforcement and evaluates structured input against declarative rules. A small in-process policy evaluator is appropriate for the fixture MVP; an OPA adapter can be introduced when identity-aware production integrations exist. Source: [Open Policy Agent documentation](https://www.openpolicyagent.org/docs).
3. **Standardised observability.** OpenTelemetry conventions standardise attributes for logs, metrics and traces; GenAI conventions also describe agent, workflow, plan and tool spans. This supports future correlation of model latency, token use, tool calls, retries and incident outcomes. Source: [OpenTelemetry semantic conventions](https://opentelemetry.io/docs/specs/semconv/), [GenAI agent span conventions](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md).
4. **Verifiable provenance.** SLSA v1.2 defines provenance and verification approaches for understanding where, when and how artifacts were produced. Fixture SHA-256 hashes are useful input integrity evidence but are not signed build attestations. Source: [SLSA v1.2](https://slsa.dev/spec/v1.2/), [SLSA provenance](https://slsa.dev/spec/v1.2/provenance).
5. **AI risk management.** NIST AI RMF and its Generative AI Profile offer a lifecycle-oriented framework for governing, mapping, measuring and managing AI risks. Source: [NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework), [NIST AI RMF Generative AI Profile](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf).
6. **API function-level authorization.** OWASP recommends default-deny authorization and explicit permission checks on every function. Source: [OWASP API Security: Broken Function Level Authorization](https://owasp.org/API-Security/editions/2023/en/0xa5-broken-function-level-authorization/), [FastAPI security utilities](https://fastapi.tiangolo.com/reference/security/).
7. **Resilient remote calls.** Microsoft reliability guidance recommends bounded retries, exponential backoff, retry budgets, idempotency for repeatable operations and circuit breakers to prevent cascading failures. Sources: [Transient fault handling](https://learn.microsoft.com/en-us/azure/architecture/best-practices/transient-faults), [Circuit breaker pattern](https://learn.microsoft.com/en-gb/azure/architecture/patterns/circuit-breaker), [Retry pattern](https://learn.microsoft.com/th-th/azure/architecture/patterns/retry).

## Implemented in this branch

### 1. Fail-closed policy decisions
- Versioned deterministic policy evaluation.
- Risk score and band from signal severity.
- Human-review flag for high/critical signals and sandbox runs.
- Explicit denylist for production writes, shell execution, credential access, autonomous deployment and destructive schema changes.
- No supported mode grants execution. Unknown modes are denied.
- Limitation: this is in-process policy evaluation, not identity-aware authorization or an OPA deployment.

### 2. Incident correlation and prioritisation
- Stable SHA-256 fingerprint based on target plus sorted unique signal types.
- Deterministic P1-P4 priority and bounded 0-100 severity score.
- Correlation patterns for pipeline-to-dashboard, freshness chains, schema-to-metric, latency-to-freshness and quality-to-metric relationships.
- Recommended next investigative steps.
- Fingerprints are grouping hints, not proof of common root cause; thresholds require calibration against representative incident history.

### 3. Tamper-evident per-run audit chain
- Hash-linked lifecycle, source provenance, policy and triage records.
- Verification detects record tampering, ordering errors, chain-link mismatches and mixed run IDs.
- API verification endpoint: GET /api/v1/runs/{run_id}/audit/verify.
- Limitation: chain is stored alongside the report and is not signed or anchored in an external append-only ledger. A database administrator could replace the whole chain; this is tamper-evidence, not non-repudiation.

### 4. Data-contract validation
- Optional baseline data contract checks for required columns, allowed columns, minimum/maximum row count and per-column null-rate ceilings.
- Contract violations become evidence-linked high-severity signals and contribute to triage.
- Constraints are opt-in so existing fixtures retain their previous behaviour.

### 5. Bounded operational metrics
- GET /api/v1/metrics summarises up to the latest 100 persisted runs with status counts, signal counts, latency summaries, human-review rate and sandbox failure rate.
- Avoids exposing run IDs as metric labels.
- It is a JSON snapshot, not an OpenTelemetry exporter, Prometheus endpoint, rolling SLO or error-budget burn-rate calculator.

### 6. API authentication and role-based access
- Protected routes require bearer tokens by default; /api/v1/health remains public.
- Tokens are represented in environment configuration by SHA-256 hashes and map to a stable actor plus one of viewer, operator, approver or admin roles.
- Read, run, request-approval and decide-approval permissions are checked separately.
- OPSPILOT_AUTH_MODE=disabled is an explicit local-development bypass only; it is not a production mode.
- Limitation: static token-hash configuration is not an identity provider, token issuer, rotation service or tenant isolation boundary.

### 7. Human approval workflow
- Approval requests capture requester, reason, expiry (30 minutes), run ID and the verified run-audit head hash.
- Approval decisions require a different actor and an approver/admin role; the decision reason is recorded in a hash-linked event history.
- Expired, already-decided and audit-invalid requests fail closed.
- Approval records explicitly state execution_performed=false; this workflow does not execute any remediation.

### 8. Idempotent run creation
- Optional Idempotency-Key header is stored only as a SHA-256 digest and scoped by actor.
- Repeated matching requests replay the original response; key reuse with a different request or a concurrent in-progress reservation returns HTTP 409.
- The SQLite reservation is transactionally claimed to reduce duplicate run creation across processes sharing the same database.

### 9. Resilience primitives
- Bounded exponential backoff with jitter, a process-local retry budget, and a thread-safe closed/open/half-open circuit breaker.
- Retrying requires the caller to explicitly declare an operation idempotent.
- Limitation: these are tested integration primitives; no real remote connector uses them yet, and the retry budget is process-local rather than distributed.

### 10. Testable controls
- Unit tests exercise policy default-deny behavior, stable fingerprints, correlation rules and audit-chain tamper detection.
- API report includes triage, policy and audit evidence.

## Recommended next implementation waves

| Priority | Mechanism | Why it matters | Acceptance criteria |
|---|---|---|---|
| P0 | Authentication and role-based authorisation | Prevents unauthorised access to run and report APIs | Default-deny, tests for reader/operator/admin roles, secrets never in logs |
| P0 | External immutable audit sink | Makes audit evidence harder to rewrite with application data | Append-only storage, integrity verification, retention policy and export |
| P0 | Real connector contract + least-privilege credentials | Avoids connector-specific code bypassing safety rules | Read-only scopes, typed timeouts, pagination/rate-limit handling, integration tests |
| P1 | OpenTelemetry traces, metrics and structured logs | Makes agent/tool latency, retries and failures observable | Trace/run correlation IDs, bounded-cardinality metrics, redaction by default |
| P1 | Data contracts and quality profiles | Extends beyond fixture-specific heuristics | Versioned schema contracts, null/volume/freshness thresholds, drift history |
| P1 | SLO/error-budget engine | Converts observations into operational decisions | Windowed success/freshness SLOs, burn-rate alerts, documented evaluation |
| P1 | Retry budget, circuit breaker and dead-letter queue | Limits cascading failures when real connectors are added | Bounded retries, jitter, idempotency key, open/half-open/closed tests |
| P1 | Human approval workflow | Creates a controlled path from recommendation to action | Actor, reason, expiry, two-person approval for high-impact changes, revalidation before execution |
| P1 | LLM evaluation and prompt-injection tests | Required before agentic reasoning or tool use | Golden set, regression thresholds, untrusted-input tests, tool allowlist, no secrets in prompts |
| P2 | Signed build provenance / SBOM / dependency audit | Improves release integrity and dependency visibility | CI-generated provenance, dependency inventory, vulnerability gate and release verification |
| P2 | Multi-tenant isolation and quotas | Needed for hosted/shared deployments | Tenant-scoped storage and queries, isolation tests, per-tenant rate and resource limits |
| P2 | Disaster recovery and rollback drills | Avoids untested recovery promises | Backups, restore test, dry-run rollback, recovery objectives documented |

## Architecture guardrails

- The model may propose a hypothesis or plan; deterministic policy and schema validation decide what is allowed.
- Treat source payloads, logs, repository files and tool outputs as untrusted data, never as instructions to change system policy.
- Use bounded retries, explicit timeouts, idempotency keys and circuit breakers around remote connectors.
- Redact secrets and sensitive payloads from logs by default. Do not capture full prompts/completions unless explicitly enabled with retention and access controls.
- Use bounded-cardinality metric labels. Do not use run IDs, dataset IDs or user IDs as Prometheus labels.
- Keep external actions disabled until connector permissions, approval, rollback and incident-response tests pass.
- Do not claim OpenTelemetry export, OPA integration, signed SLSA provenance or production readiness until those integrations exist and are verified.


## Implementation update: ETags, watermarks, agent graph and tracing

### Conditional HTTP reads and ETags

- `ConditionalHTTPConnector` is a bounded, read-only HTTPS GET connector. It requires an explicit hostname allowlist, rejects credentials embedded in URLs, forbids non-HTTPS URLs and cross-allowlist redirects, applies a timeout and response-size cap, and has no write method or arbitrary authorization-header option.
- It sends `If-None-Match` and `If-Modified-Since` when validators are cached. A `304 Not Modified` reuses the previously stored representation; a `200` updates the cache. Cache keys are SHA-256 URL digests to avoid storing query-string values as keys.
- Run-detail and run-report GET endpoints now return stable SHA-256 ETags and honour `If-None-Match`, including weak validators and wildcard matching.
- Limitation: the generic connector is not yet wired to a configured production source, secret manager, distributed cache, rate-limit-aware scheduler or source-specific pagination adapter. The connector does not claim that a 304 is a source-data watermark.

Research: [GitHub REST API best practices and conditional requests](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api), [HTTP conditional requests](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Conditional_requests).

### Durable incremental-sync watermarks

- `SyncStateStore` persists source representation cache and sync checkpoints in SQLite.
- Checkpoint updates use an explicit expected revision (compare-and-swap) and a transaction, preventing stale concurrent workers from silently overwriting a newer checkpoint.
- Numeric and ISO-8601 timestamp watermarks are supported; backwards movement, opaque string cursors and type changes fail closed.
- **Commit protocol:** fetch and validate source changes; write/merge the destination batch idempotently; commit the destination; only then call `commit_checkpoint` with the revision read at the start of the run. If destination commit fails, do not advance the watermark. For a destination and checkpoint in different databases, use an idempotent sink plus replay/reconciliation because this library cannot provide a cross-system atomic transaction.
- Watermarks based only on monotonically increasing timestamps/IDs can miss deletes and can miss late-arriving updates when the source column is not reliable. Prefer CDC/change tracking or source-native change tokens when they exist; use an overlap window plus deduplication for timestamp feeds, and explicitly test ties, late arrivals, timezone normalization, nulls, deletes, and backfills.
- `IncrementalSyncRunner` now coordinates source high-watermark discovery, bounded batch reads, an explicitly idempotent sink callback, and checkpoint advancement only after the sink callback returns successfully. Optional timestamp overlap supports late-arriving rows at the cost of replaying duplicates.
- Limitation: no warehouse destination transaction or production ingestion scheduler is connected yet. Opaque pagination cursors are deliberately not treated as sortable watermarks. A crash after sink commit but before checkpoint commit can replay a batch, so the sink must be idempotent.

Research: [Microsoft Fabric incremental copy and CDC versus watermarks](https://learn.microsoft.com/en-us/fabric/data-factory/incremental-copy-job), [Azure Data Factory incremental copy pattern](https://learn.microsoft.com/en-us/azure/data-factory/tutorial-incremental-copy-overview).

### Bounded agent workflow

The incident service now runs a fixed five-stage deterministic workflow:

1. Evidence validation and canonical SHA-256 digest.
2. Incident triage and correlation.
3. Policy gate using the existing fail-closed evaluator.
4. Recommendation planning based on observed signals.
5. Safety evaluation to assert that execution and production writes remain disabled.

Each stage emits a bounded event with duration, status and output digest. Duplicate signal IDs, excessive signal counts and failed invariants stop the workflow. The report exposes the workflow outcome and recommendations. Agents have no dynamic tool registry, no shell access, no write connector and no LLM provider in this phase. This is a real orchestration seam with deterministic agents, not a claim of autonomous LLM reasoning.

Before introducing an LLM, add a versioned golden evaluation set, prompt-injection and tool-abuse tests, model/provider timeouts, output schema validation, independent policy checks, privacy redaction, cost budgets, and human approval for any high-impact action. Source records, repository content, logs and model output must remain untrusted data—not policy instructions.

Research: [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/), [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework).

### Request correlation and OpenTelemetry

- Every API request receives an `X-Request-ID`; a valid caller-supplied value is propagated, otherwise a new ID is generated.
- Request logs are JSON records with method, path (not query string), status, duration and request ID. Request bodies, authorization headers, query values and exception messages are intentionally excluded.
- Optional OTLP tracing is available with `pip install -e ".[otel]"`, `OPSPILOT_OTEL_ENABLED=true`, and `OTEL_EXPORTER_OTLP_ENDPOINT` set. It is disabled by default and fails fast if explicitly enabled without its endpoint/dependencies.
- Limitation: this adds trace instrumentation and correlation, not a complete OpenTelemetry metrics/logs exporter, alerting backend or distributed SLO/error-budget service.

Research: [OpenTelemetry Python instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/), [FastAPI instrumentation](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html).

### Release acceptance gates for this wave

- CI on Python 3.11 and 3.12 must pass unit tests, lint, and the existing fixture benchmark.
- Tests must cover ETag cache hit/304 replay, URL allowlist and response bounds, watermark monotonicity and optimistic concurrency, agent failure handling, no-execution invariants, request IDs and API conditional GET.
- These mechanisms are foundations for the next connector wave; they do not make the repository production-ready.


### Read-only public GitHub source adapter

- `GitHubReadOnlyConnector` provides bounded repository metadata, latest-commit metadata, and workflow-run summaries using fixed GET endpoints and the conditional HTTP cache.
- Owner/repository slugs are validated, branch refs are encoded as path segments, pagination is bounded, and responses are projected onto allowlisted fields rather than returned wholesale.
- The adapter is public-data only and has no credential parameter. It does not yet implement private-repository access, webhooks, authenticated rate-limit budgets, pagination across every page, or scheduled polling. Those require a dedicated secret-managed read-only GitHub App integration.
- For scheduled production monitoring, prefer webhooks over frequent polling where possible. When polling is required, use stable URLs, conditional requests, explicit rate-limit handling, and bounded serial requests.

Research: [GitHub REST API best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api).


### Signed event-driven GitHub intake

- The webhook endpoint verifies `X-Hub-Signature-256` against the exact request bytes using HMAC-SHA256 and constant-time comparison, validates event names, enforces a 1 MB payload ceiling, and deduplicates `X-GitHub-Delivery` in SQLite.
- Only a payload digest and allowlisted bounded metadata are persisted. Same-delivery/same-payload retries are idempotent; delivery-ID reuse with a different payload is rejected.
- The endpoint is intentionally an inbox only: it does not trigger agents or remediation. The next production step is a durable worker/queue with retry limits, dead-letter handling, idempotent consumers, delivery-failure metrics and operational replay controls.
- A shared webhook secret is a credential: provision it through a secret manager, rotate it with a documented overlap procedure, terminate TLS at the trusted perimeter, rate-limit the endpoint, and keep request bodies out of logs. Delivery deduplication retention is currently 90 days.

Research: [GitHub REST API integration best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api), [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/).
