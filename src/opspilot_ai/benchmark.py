"""Reproducible local fixture benchmark; not a production-accuracy claim."""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from . import __version__
from .service import analyze_fixture


def run_benchmark(fixture_root: str | Path, output: str | Path | None = None) -> dict[str, Any]:
    root = Path(fixture_root).resolve()
    if not root.is_dir():
        raise ValueError("Fixture root does not exist.")
    cases = sorted(path for path in root.iterdir() if path.is_dir())
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="opspilot-benchmark-") as temporary:
        db = Path(temporary) / "runs.sqlite3"
        for case in cases:
            hashes = {
                file.name: hashlib.sha256(file.read_bytes()).hexdigest()
                for file in sorted(case.iterdir())
                if file.is_file()
            }
            result = analyze_fixture(case.name, root, db, "dry_run")
            rows.append({
                "case": case.name,
                "fixture_sha256": hashes,
                "run_id": result.run_id,
                "status": result.status,
                "signal_types": sorted({signal.signal_type for signal in result.signals}),
                "signal_count": len(result.signals),
                "hypothesis_count": len(result.hypotheses),
                "duration_ms": result.duration_ms,
                "lifecycle_events": result.lifecycle_events,
            })
    report = {
        "schema_version": 1,
        "benchmark_name": "opspilot-fixture-operations",
        "opspilot_version": __version__,
        "generated_at": datetime.now(UTC).isoformat(),
        "fixture_root": root.name,
        "fixture_count": len(rows),
        "completed_runs": sum(row["status"] == "completed" for row in rows),
        "failed_runs": sum(row["status"] == "failed" for row in rows),
        "cases": rows,
        "limitations": [
            "Synthetic fixture evaluation only; not production accuracy.",
            "No precision/recall/F1 is reported because independently adjudicated ground truth is not defined here.",
            "Historical RepoSentinel benchmark outputs are not recomputed or overwritten.",
        ],
    }
    if output is not None:
        destination = Path(output).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the reproducible OpsPilot AI fixture benchmark")
    parser.add_argument("--fixtures", default="examples/ops_cases")
    parser.add_argument("--output", default="artifacts/opspilot_fixture_benchmark.json")
    args = parser.parse_args()
    report = run_benchmark(args.fixtures, args.output)
    print(
        f"fixtures={report['fixture_count']} completed={report['completed_runs']} "
        f"failed={report['failed_runs']} output={Path(args.output)}"
    )
    for row in report["cases"]:
        print(f"{row['case']:36} signals={row['signal_count']:2} status={row['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
