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
$token = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
$sha = [System.Security.Cryptography.SHA256]::Create()
$hash = [BitConverter]::ToString($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($token))).Replace("-", "").ToLowerInvariant()
$tokenMap = @{}; $tokenMap[$hash] = @{ role = "admin"; actor = "local-admin" }
$env:OPSPILOT_API_TOKEN_HASHES = ($tokenMap | ConvertTo-Json -Compress)
$env:OPSPILOT_AUTH_MODE = "required"
Write-Host "Save this API token securely: $token"
uvicorn opspilot_ai.api:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for the local OpenAPI interface. The API binds to localhost by default in these instructions. Do not expose it publicly without authentication and a deployment security review.

## API quick test

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
$headers = @{ Authorization = "Bearer $token" }
$body = @{ target = "demo_warehouse"; connector = "fixture"; mode = "analyze"; remediation_mode = "dry_run" } | ConvertTo-Json
$result = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/runs -Headers $headers -ContentType "application/json" -Body $body
$result
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/runs/$($result.run_id)" -Headers $headers
```

## Configuration

- `OPSPILOT_FIXTURE_ROOT`: directory containing one folder per fixture.
- `OPSPILOT_DB_PATH`: local SQLite database path.

The API accepts only the fixture connector and `read_only`, `dry_run` or `sandbox` modes. Sandbox mode performs allowlisted JSON fixture changes on a disposable copy and reports validation. It never executes shell commands or writes to production.

## Tests and current limits

Run `pytest -q`. The current MVP tests cover fixture detection, persistence, input traversal rejection and the API health endpoint. The inherited RepoSentinel engine and historical benchmarks have not yet been migrated into this repository; their results must not be described as OpsPilot AI benchmark results.


## Run the reproducible fixture benchmark

Run all configured cases and write a separate report:

```powershell
opspilot-benchmark --fixtures examples/ops_cases --output artifacts/opspilot_fixture_benchmark.json
```

The benchmark records the OpsPilot version, generation timestamp, each fixture file's SHA-256 hash, detected signal types and run durations. It does not overwrite inherited RepoSentinel artifacts and does not claim production accuracy. The generated `artifacts/` directory is ignored by Git by default.


## API authentication and role configuration

Authentication is required by default. Create a high-entropy token for each service or operator, then store only its SHA-256 digest in the environment configuration. The configuration is a JSON object mapping each digest to a role and stable actor ID.

Generate a token hash in PowerShell:

```powershell
$token = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
$bytes = [System.Text.Encoding]::UTF8.GetBytes($token)
$sha = [System.Security.Cryptography.SHA256]::Create()
$hash = [Convert]::ToHexString($sha.ComputeHash($bytes)).ToLowerInvariant()
$token  # Save securely in your secret manager; do not commit it
$hash
```

Configure the API process with the hash, never the raw token:

```powershell
$env:OPSPILOT_API_TOKEN_HASHES = '{"REPLACE_WITH_SHA256_HASH":{"role":"admin","actor":"local-admin"}}'
$env:OPSPILOT_AUTH_MODE = "required"
uvicorn opspilot_ai.api:app --host 127.0.0.1 --port 8000
```

Roles: viewer reads; operator reads, runs analyses and requests approval; approver reads and decides approval requests; admin can do all of these. Requesters cannot approve their own requests. The health endpoint is public. OPSPILOT_AUTH_MODE=disabled is for local unit tests/development only and must never be used on an exposed service.

## API safety controls

- Add Authorization: Bearer <token> to protected requests.
- Optional Idempotency-Key on POST /api/v1/runs prevents duplicate run records for matching requests and replays the first response.
- POST /api/v1/runs/{run_id}/approvals opens a 30-minute review request; POST /api/v1/approvals/{approval_id}/decision records an approved/rejected decision. Neither endpoint executes a plan.
- Retry/circuit-breaker primitives are not wired to any real connector in this fixture-only MVP.


## API authentication and role configuration

Authentication is required by default. Create a high-entropy token for each service or operator, then store only its SHA-256 digest in OPSPILOT_API_TOKEN_HASHES. The configuration is a JSON object mapping each digest to a role and stable actor ID.

Generate a token hash in PowerShell:

```powershell
$token = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
$bytes = [System.Text.Encoding]::UTF8.GetBytes($token)
$sha = [System.Security.Cryptography.SHA256]::Create()
$hash = [Convert]::ToHexString($sha.ComputeHash($bytes)).ToLowerInvariant()
$token  # Save securely; do not commit it
$hash
```

Roles: viewer reads; operator runs analyses and requests approval; approver decides approval requests; admin has all permissions. Requesters cannot approve their own requests. The health endpoint is public. OPSPILOT_AUTH_MODE=disabled is for local development/tests only and must never be used on an exposed service.

The optional Idempotency-Key header on POST /api/v1/runs replays the original response for matching repeat requests. Approval endpoints record human decisions but do not execute remediation. Retry/circuit-breaker primitives are not wired to real connectors yet.
