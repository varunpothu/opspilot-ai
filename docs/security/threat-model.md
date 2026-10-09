# OpsPilot AI threat model

## Scope

This threat model covers the local fixture-backed MVP. It does not cover production connectors because none are implemented in this package.

## Assets

- Fixture JSON files and their integrity.
- Run records and evidence hashes in the local SQLite database.
- Generated reports and sandbox validation output.
- Local filesystem paths and environment configuration.
- Integrity of the CI and benchmark results.

## Trust boundaries

1. **HTTP/CLI input to application:** target names and mode values are untrusted. Pydantic validation, a strict target-name pattern and mode allowlists reject unsupported input.
2. **Fixture root to collector:** fixtures are data, never executable instructions. The connector resolves paths, rejects target traversal and symlink escapes, limits each fixture to 1 MB, requires four named JSON files and validates UTF-8 JSON objects.
3. **Analysis to hypothesis:** deterministic signals are distinct from candidate hypotheses. Hypotheses reference signal IDs and are not represented as verified root causes.
4. **Planner to sandbox:** no arbitrary shell command is accepted or executed. The sandbox copies a single validated fixture directory into a disposable temporary directory and only changes allowlisted JSON fields.
5. **Sandbox to validation:** postconditions must pass for sandbox validation to report passed. A failed validation causes the run to be marked failed.
6. **Application to persistence:** run data is stored in local SQLite. This MVP does not provide authentication or multi-tenant separation.
7. **Local service to network:** the documented launch command binds to 127.0.0.1. Public exposure is unsupported.

## Abuse cases and mitigations

| Abuse case | Current mitigation |
|---|---|
| Directory traversal in target | Strict target regex and resolved-root checks |
| Symlink escape from fixture root | Resolve each expected file and require it to remain inside the target |
| Oversized fixture JSON | 1 MB per-file limit |
| Malformed JSON or invalid Unicode | Controlled connector error |
| Unsupported connector or remediation mode | Pydantic literal allowlists |
| Prompt-injected command in fixture text | No LLM is invoked and no shell commands are executed |
| Accidental production mutation | No production connector; sandbox writes only to a disposable copy |
| False success after failed validation | Failed sandbox validation transitions the run to failed |
| Historical benchmark contamination | New benchmark output is separate and includes fixture hashes |

## Known gaps

- No authentication, authorization or user identity.
- No rate limiting, concurrency limits or request idempotency key.
- No retention/cleanup command for local SQLite history.
- No secret redaction layer is needed for the current fixture-only schema, but must be added before collecting real logs or credentials.
- No external dependency or secret scanning step in CI yet.
- No independent security review.
- The original RepoSentinel agents and sandbox have not yet been migrated and reviewed through this API.

## Production gate

Do not expose this API to a public network or connect it to production systems until authentication, authorization, least-privilege connector credentials, request limits, audit identity, secret redaction, monitoring, retention, threat review and integration-specific security tests are implemented.
