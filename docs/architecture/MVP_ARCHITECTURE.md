# OpsPilot AI MVP architecture

## Current request flow

1. A CLI command or local FastAPI request names a fixture target.
2. The service validates the target name and resolves it beneath the configured fixture root.
3. The fixture adapter reads four JSON documents: source, pipeline, dashboard and baseline.
4. Deterministic checks create structured signals with stable IDs and evidence references.
5. Simple rules derive candidate hypotheses from signals. These are not AI model outputs and are not confirmed root causes.
6. The service creates a review-only remediation plan when signals exist.
7. The full result is persisted in SQLite and returned as a typed response.

## Trust boundaries

- **Caller input:** untrusted. Validate target names and supported enum values.
- **Fixture directory:** local input data. Expected files are allowlisted; resolved paths must remain within the target.
- **Analysis engine:** deterministic MVP checks. It does not run fixture content as code.
- **Remediation:** planning only. No action executor exists in the current MVP.
- **Persistence:** local SQLite. Do not store sensitive input data.
- **API:** intended for local development. Authentication is not implemented.

## Failure semantics

Malformed or missing fixture data raises a controlled input error. Unknown targets do not run. API request validation rejects unsupported connectors or modes. A run result is only persisted after analysis has produced a typed result.

## Evolution path

1. Migrate the original RepoSentinel operations engine behind an adapter.
2. Introduce explicit lifecycle events and stronger run-level failure records.
3. Add an integration protocol with a fixture adapter as the reference implementation.
4. Add read-only connectors (for example, GitHub or dbt artifacts) after permission and secret handling are tested.
5. Add an isolated sandbox executor only after a threat model, resource limits, action allowlists and post-action validation are in place.
6. Add a web UI after API contracts stabilize.

## Deliberate omissions

There is no distributed queue, LLM orchestration framework, vector database, production connector, automatic production write, or multi-tenant service in this MVP. These are not required to prove the initial workflow and would add operational complexity prematurely.
