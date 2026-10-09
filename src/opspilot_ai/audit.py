"""Tamper-evident per-run audit-chain helpers."""
from __future__ import annotations

import hashlib
import json
from typing import Any

GENESIS = "0" * 64


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def build_audit_chain(
    run_id: str,
    lifecycle_events: list[dict[str, Any]],
    source_hashes: dict[str, str],
    policy_decision: dict[str, Any],
    triage: dict[str, Any],
) -> list[dict[str, Any]]:
    """Hash-link lifecycle, provenance, policy, and triage records for one run."""
    records: list[dict[str, Any]] = []
    previous_hash = GENESIS
    entries = [
        {"event_type": "run_lifecycle", "payload": event} for event in lifecycle_events
    ] + [
        {"event_type": "source_provenance", "payload": {"source_hashes": source_hashes}},
        {"event_type": "policy_decision", "payload": policy_decision},
        {"event_type": "incident_triage", "payload": triage},
    ]
    for index, entry in enumerate(entries):
        body = {
            "sequence": index,
            "run_id": run_id,
            "previous_hash": previous_hash,
            "event_type": entry["event_type"],
            "payload": entry["payload"],
        }
        record_hash = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
        record = {**body, "record_hash": record_hash}
        records.append(record)
        previous_hash = record_hash
    return records


def verify_audit_chain(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify ordering, hash integrity, and links; this is not a signed external ledger."""
    previous_hash = GENESIS
    errors: list[str] = []
    run_id: str | None = None
    for expected_sequence, record in enumerate(records):
        if record.get("sequence") != expected_sequence:
            errors.append(f"sequence_mismatch:{expected_sequence}")
        if record.get("previous_hash") != previous_hash:
            errors.append(f"previous_hash_mismatch:{expected_sequence}")
        if run_id is None:
            run_id = record.get("run_id")
        elif record.get("run_id") != run_id:
            errors.append(f"run_id_mismatch:{expected_sequence}")
        body = {key: record.get(key) for key in ("sequence", "run_id", "previous_hash", "event_type", "payload")}
        expected_hash = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
        if record.get("record_hash") != expected_hash:
            errors.append(f"record_hash_mismatch:{expected_sequence}")
        previous_hash = str(record.get("record_hash", ""))
    if not records:\n        errors.append("empty_chain")\n    return {"valid": bool(records) and not errors, "record_count": len(records), "run_id": run_id, "head_hash": previous_hash if records else GENESIS, "errors": errors}
