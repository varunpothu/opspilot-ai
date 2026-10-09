# OpsPilot AI

**Evidence-driven data and AI operations**

OpsPilot AI is a local-first engineering operations project focused on investigating data pipeline and AI workload incidents. The intended workflow combines deterministic reliability checks, structured evidence, root-cause hypotheses, sandbox-first remediation, and post-action validation.

> **Project status:** MVP planning and migration. This repository is being established to evolve the existing RepoSentinel codebase. Features described as planned are not yet implemented in this repository.

## Goals

- Detect selected data reliability conditions from controlled inputs.
- Produce findings with evidence and provenance.
- Keep hypotheses distinct from verified facts.
- Propose remediation and validate it in an isolated sandbox.
- Persist incident runs and export auditable reports.
- Build a small API and reliable automated test suite.

## Safety principles

- Read-only by default.
- No production writes in the MVP.
- No arbitrary command execution from AI-generated content.
- Failed validation must never be reported as a successful recovery.
- Logs and reports must redact secrets.

## Planned MVP stack

- Python 3.11+
- FastAPI and Pydantic
- SQLite through a persistence abstraction
- pytest and httpx
- Ruff for linting and formatting
- Docker Compose later, after the local workflow is stable

These are the intended MVP technologies, not a statement that the implementation is complete.

## Development plan

Read [`docs/MVP_IMPLEMENTATION_SPEC.md`](docs/MVP_IMPLEMENTATION_SPEC.md) for the detailed architecture, API contracts, database schema, security requirements, tests, migration plan, and phased tasks.

The first milestone is to reproduce the inherited baseline and preserve existing benchmark artifacts before changing the engine.

## Evaluation

Historical benchmark results from the inherited codebase must remain clearly separated from new evaluation results. Synthetic fixture scores describe performance on those fixtures only and must not be presented as general production accuracy.

## Status labels

Documentation and UI should distinguish **Implemented**, **Fixture/demo**, **Planned**, and **Not supported**. Do not claim a real connector, production deployment, or autonomous recovery until it is implemented and tested.
