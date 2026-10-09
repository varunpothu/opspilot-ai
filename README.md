# OpsPilot AI

**Evidence-driven data and AI operations**

OpsPilot AI is a local-first project for investigating data pipeline and AI workload incidents. The current MVP reads controlled JSON fixtures, runs deterministic reliability checks, attaches evidence to findings, proposes candidate explanations, and persists results to SQLite.

> **Status: early MVP.** The first API and fixture-analysis slice is implemented. The original RepoSentinel engine and its historical benchmarks have not yet been migrated into this repository. This is not a production-ready incident response system.

## Implemented in the current repository

- Python package and `opspilot` CLI.
- Fixture-backed checks for pipeline status, schema drift, row-count anomalies, source freshness and dashboard staleness.
- Structured findings with evidence references and stable identifiers.
- Rule-based root-cause hypotheses explicitly labelled as hypotheses.
- Review-only remediation plans. **No remediation actions are executed.**
- SQLite persistence for incident runs.
- FastAPI health, create-run, list-runs, detail and report endpoints.
- Five inherited-style data operations fixtures covering pipeline failure, schema drift, null-rate spike, volume drop and healthy operation.\n- Explicit run lifecycle state machine and fixture connector with SHA-256 provenance.\n- Disposable sandbox simulation with allowlisted JSON changes and post-repair validation.\n- CLI/API support for read-only, dry-run and sandbox modes.\n- CI workflow, installation guide and security notes.

## Not implemented yet

- Migration of the complete RepoSentinel codebase, all original agents, example cases and benchmark artifacts.
- Real GitHub, dbt, SQL warehouse, AWS, monitoring or model-serving connectors.
- LLM-based reasoning or agent orchestration in this new MVP package.
- Executable sandbox repair, production actions, human approval UI or rollback.
- Authentication, multi-tenant isolation, production deployment or a React dashboard.

## Quick start

Requires Python 3.11 or newer.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
pytest -q
```

Run a sample analysis:

```powershell
opspilot --target 01_pipeline_failure_stale_dashboard --fixtures examples/ops_cases --db .opspilot/opspilot.sqlite3 --remediation-mode sandbox --output artifacts/demo-result.json
```

Start the local API:

```powershell
$env:OPSPILOT_FIXTURE_ROOT = "examples/ops_cases"
$env:OPSPILOT_DB_PATH = ".opspilot/opspilot.sqlite3"
uvicorn opspilot_ai.api:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for the local API docs. Full instructions are in [INSTALL.md](INSTALL.md).

## Documentation

- [MVP implementation specification](docs/MVP_IMPLEMENTATION_SPEC.md)
- [Current implementation status](docs/STATUS.md)\n- [RepoSentinel migration record](docs/REPOSENTINEL_MIGRATION.md)
- [MVP architecture and trust boundaries](docs/architecture/MVP_ARCHITECTURE.md)
- [Security policy](SECURITY.md)

## Safety

The current service reads fixture files and stores run records locally. Sandbox mode applies only allowlisted changes to a disposable copy and validates the result. It never executes shell commands or modifies source fixtures. Keep the API on localhost; authentication is not implemented.

## Evaluation

Historical benchmark results from the inherited RepoSentinel archive have not been migrated or rerun against OpsPilot AI. Synthetic fixture scores describe only the dataset and evaluator that produced them; do not present them as general production accuracy.

## Status labels

Documentation should distinguish **Implemented**, **Fixture/demo**, **Planned**, and **Not supported**. Do not claim a real connector, production deployment or autonomous recovery until it is implemented and tested.
