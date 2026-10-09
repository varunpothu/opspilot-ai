"""Deterministic, optional data-contract checks for fixture-backed source snapshots."""
from __future__ import annotations

from typing import Any


def evaluate_data_contract(source: dict[str, Any], baseline: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate explicitly configured contract constraints; absent constraints are ignored."""
    contract = baseline.get("data_contract")
    if not isinstance(contract, dict):
        return []
    violations: list[dict[str, Any]] = []
    schema = source.get("schema")
    schema_fields = set(schema) if isinstance(schema, list) and all(isinstance(x, str) for x in schema) else None

    required = contract.get("required_columns")
    if isinstance(required, list) and all(isinstance(x, str) for x in required) and schema_fields is not None:
        missing = sorted(set(required) - schema_fields)
        if missing:
            violations.append({
                "rule": "required_columns",
                "field": "source.schema",
                "observed": schema,
                "expected": required,
                "detail": f"Required contract columns are missing: {', '.join(missing)}",
            })

    allowed = contract.get("allowed_columns")
    if isinstance(allowed, list) and all(isinstance(x, str) for x in allowed) and schema_fields is not None:
        unexpected = sorted(schema_fields - set(allowed))
        if unexpected:
            violations.append({
                "rule": "allowed_columns",
                "field": "source.schema",
                "observed": schema,
                "expected": allowed,
                "detail": f"Columns outside the contract were found: {', '.join(unexpected)}",
            })

    row_count = source.get("row_count")
    minimum = contract.get("min_row_count")
    maximum = contract.get("max_row_count")
    if isinstance(row_count, (int, float)) and not isinstance(row_count, bool):
        if isinstance(minimum, (int, float)) and row_count < minimum:
            violations.append({
                "rule": "min_row_count", "field": "source.row_count",
                "observed": row_count, "expected": minimum,
                "detail": f"Row count {row_count} is below contract minimum {minimum}.",
            })
        if isinstance(maximum, (int, float)) and row_count > maximum:
            violations.append({
                "rule": "max_row_count", "field": "source.row_count",
                "observed": row_count, "expected": maximum,
                "detail": f"Row count {row_count} is above contract maximum {maximum}.",
            })

    null_rates = source.get("null_rates")
    null_limits = contract.get("max_null_rates")
    if isinstance(null_rates, dict) and isinstance(null_limits, dict):
        for column, limit in null_limits.items():
            observed = null_rates.get(column)
            if (isinstance(observed, (int, float)) and not isinstance(observed, bool)
                    and isinstance(limit, (int, float)) and not isinstance(limit, bool)
                    and observed > limit):
                violations.append({
                    "rule": "max_null_rate",
                    "field": f"source.null_rates.{column}",
                    "observed": observed,
                    "expected": limit,
                    "detail": f"Null rate for {column} exceeds contract maximum {limit}.",
                })
    return violations
