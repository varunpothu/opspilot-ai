# Local installation

OpsPilot AI currently runs against local JSON fixtures. It does not connect to production systems or execute remediation actions.

## Prerequisites

- Python 3.11 or newer
- Git (optional if downloading the repository ZIP)

## Windows PowerShell

From the repository root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
pytest -q
```

If PowerShell blocks activation, use the Python executable inside `.venv\Scripts\python.exe` directly.

## Run a sample analysis

```powershell
opspilot --target 01_pipeline_failure_stale_dashboard --fixtures examples/ops_cases --db .opspilot/opspilot.sqlite3 --remediation-mode sandbox --output artifacts/demo-result.json
```

The command prints a JSON result and optionally writes the same result to the output path. In sandbox mode, changes are applied only to a temporary copy, then validated. Original fixture bytes are checked for integrity. No shell commands or production writes are used.

## Start the API

```powershell
$env:OPSPILOT_FIXTURE_ROOT = "examples/ops_cases"
$env:OPSPILOT_DB_PATH = ".opspilot/opspilot.sqlite3"
uvicorn opspilot_ai.api:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for the local OpenAPI interface. The API binds to localhost by default in these instructions. Do not expose it publicly without authentication and a deployment security review.

## API quick test

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
$body = @{ target = "demo_warehouse"; connector = "fixture"; mode = "analyze"; remediation_mode = "dry_run" } | ConvertTo-Json
$result = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/runs -ContentType "application/json" -Body $body
$result
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/runs/$($result.run_id)"
```

## Configuration

- `OPSPILOT_FIXTURE_ROOT`: directory containing one folder per fixture.
- `OPSPILOT_DB_PATH`: local SQLite database path.

The API accepts only the fixture connector and `read_only`, `dry_run` or `sandbox` modes. Sandbox mode performs allowlisted JSON fixture changes on a disposable copy and reports validation. It never executes shell commands or writes to production.

## Tests and current limits

Run `pytest -q`. The current MVP tests cover fixture detection, persistence, input traversal rejection and the API health endpoint. The inherited RepoSentinel engine and historical benchmarks have not yet been migrated into this repository; their results must not be described as OpsPilot AI benchmark results.
