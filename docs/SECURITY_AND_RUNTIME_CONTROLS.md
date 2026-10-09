# Security and runtime controls

**Status:** Implemented fixture-MVP controls; not a production security certification.

## Authentication

All API endpoints except GET /api/v1/health require a bearer token by default. Configure OPSPILOT_API_TOKEN_HASHES as a JSON object where each key is a SHA-256 digest of a high-entropy token and each value contains a role and stable actor identifier:

```json
{
  "REPLACE_WITH_SHA256_TOKEN_HASH": {
    "role": "admin",
    "actor": "local-admin"
  }
}
```

Roles:
- viewer: read runs, reports, metrics and approval records.
- operator: viewer permissions plus run analysis and request approval.
- approver: viewer permissions plus approve/reject requests.
- admin: all listed permissions.

Generate a high-entropy token and hash it locally; store the raw token in a secret manager or protected environment, never in source control. Static token maps do not provide token issuance, expiration, rotation, SSO, revocation propagation or multi-tenant isolation.

OPSPILOT_AUTH_MODE=disabled explicitly bypasses authentication for local development/tests only. Never use it on a network-exposed service. The API instructions bind to localhost.

## Approval workflow

1. An operator creates an analysis run.
2. The operator submits a reason to POST /api/v1/runs/{run_id}/approvals.
3. OpsPilot verifies the run audit chain, captures its head hash and creates a 30-minute pending request.
4. A different actor with the approver or admin role records approved or rejected with a decision reason.
5. The approval event chain can be checked at GET /api/v1/approvals/{approval_id}/audit/verify.

An approval means only that a human recorded a decision about a proposed plan. It does not execute remediation, grant a connector permission or authorize a production write. Requests that are expired, already decided or based on an invalid run audit chain are rejected.

## Idempotency

POST /api/v1/runs accepts an optional Idempotency-Key header (8-200 characters). The key is hashed before persistence and scoped by actor. A matching repeat returns the original response; reusing the key with a different payload or while the original is still processing returns HTTP 409. Reservations use SQLite transactions, but this is not a distributed idempotency guarantee across separate database instances.

## Resilience primitives

opspilot_ai.resilience provides:
- Bounded retry attempts (at most five total attempts).
- Exponential backoff with jitter.
- Process-local retry budget.
- Thread-safe circuit breaker with closed, open and half-open behavior.
- Retry refusal unless the caller explicitly declares the operation idempotent.

These primitives are not yet wired to production connectors. A connector must define timeouts, transient exception types, idempotency semantics, secret redaction and integration tests before opting in.

## Remaining production gates

- Replace static token hashes with a managed identity provider or an equivalent production token lifecycle.
- Add rate limits, concurrency/resource quotas and tenant isolation where required.
- Move audit events to a separately administered append-only store and add signed/verified build provenance.
- Add OpenTelemetry exporters, secret redaction, retention policies, alerting and external connector security tests.
- Review the deployment perimeter and use TLS when traffic leaves localhost.
