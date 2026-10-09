"""Command-line entry point for local fixture-backed analysis."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .service import IncidentInputError, analyze_fixture


def main() -> int:
    parser = argparse.ArgumentParser(description="OpsPilot AI fixture-backed incident analysis")
    parser.add_argument("--target", required=True, help="Fixture directory name under fixture root")
    parser.add_argument("--fixtures", default=os.getenv("OPSPILOT_FIXTURE_ROOT", "examples/ops_cases"))
    parser.add_argument("--db", default=os.getenv("OPSPILOT_DB_PATH", ".opspilot/opspilot.sqlite3"))
    parser.add_argument("--output", help="Optional path for a JSON result export")
    parser.add_argument("--remediation-mode", choices=("read_only", "dry_run", "sandbox"), default="dry_run", help="Sandbox only edits a disposable fixture copy and validates it")
    args = parser.parse_args()
    try:
        result = analyze_fixture(args.target, Path(args.fixtures), Path(args.db), args.remediation_mode)
    except IncidentInputError as exc:
        parser.error(str(exc))
    rendered = result.model_dump_json(indent=2)
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
