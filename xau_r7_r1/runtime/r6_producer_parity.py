from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .constants import (
    CANONICAL_R6_ZIP_SHA256,
    RETIRED_SOURCE,
    R6_DECISION_POLICY,
    R6_DECISION_SCHEMA,
    R6_SOURCE_PRIORITY,
)
from .r6_integrity import sha256_file
from .r6_producer_admission import PARITY_SCHEMA


class ProducerParityError(RuntimeError):
    pass


PARITY_TOOL_VERSION = "R7_R1_R6_PRODUCER_PARITY_TOOL_V2"
ISOLATION_SCHEMA = "V16_R6_CAUSAL_FIXTURE_ISOLATION_V1"

_RECORD_FIELDS = {"fixture_id", "available_through_ms", "decision"}
_DECISION_FIELDS = {
    "schema", "policy", "parent_zip_sha256", "decision_id", "signal_bar_ms",
    "emitted_at_ms", "side", "source", "priority", "family", "signal_type",
    "atr_usd", "stop_atr", "target_atr", "geometry_used", "lot_size", "admitted",
}
_SELECTION_FIELDS = (
    "decision_id", "signal_bar_ms", "side", "source", "priority", "family",
    "signal_type", "admitted",
)
_GEOMETRY_FIELDS = ("atr_usd", "stop_atr", "target_atr", "geometry_used")


def _strict_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProducerParityError(name + "_MUST_BE_INTEGER")
    return int(value)


def _finite_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ProducerParityError(name + "_MUST_BE_NUMERIC")
    try:
        result = float(value)
    except Exception as exc:
        raise ProducerParityError(name + "_INVALID") from exc
    if not math.isfinite(result):
        raise ProducerParityError(name + "_NONFINITE")
    return result


def _load_json(path: Path, label: str) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise ProducerParityError(label + "_UNREADABLE") from exc
    if not isinstance(data, dict):
        raise ProducerParityError(label + "_INVALID")
    return data


def _validate_decision(decision: Any, label: str) -> Optional[Dict[str, Any]]:
    if decision is None:
        return None
    if not isinstance(decision, dict):
        raise ProducerParityError(label + "_DECISION_MUST_BE_OBJECT_OR_NULL")
    unknown = set(decision) - _DECISION_FIELDS
    missing = _DECISION_FIELDS - set(decision)
    if unknown:
        raise ProducerParityError(label + "_DECISION_UNKNOWN_FIELDS:" + ",".join(sorted(unknown)))
    if missing:
        raise ProducerParityError(label + "_DECISION_MISSING_FIELDS:" + ",".join(sorted(missing)))
    if decision["schema"] != R6_DECISION_SCHEMA:
        raise ProducerParityError(label + "_DECISION_SCHEMA_MISMATCH")
    if decision["policy"] != R6_DECISION_POLICY:
        raise ProducerParityError(label + "_DECISION_POLICY_MISMATCH")
    if str(decision["parent_zip_sha256"]).lower() != CANONICAL_R6_ZIP_SHA256:
        raise ProducerParityError(label + "_DECISION_PARENT_SHA_MISMATCH")
    if not isinstance(decision["decision_id"], str) or not decision["decision_id"]:
        raise ProducerParityError(label + "_DECISION_ID_INVALID")
    if not isinstance(decision["source"], str) or decision["source"] not in R6_SOURCE_PRIORITY:
        raise ProducerParityError(label + "_DECISION_SOURCE_INVALID")
    if not isinstance(decision["family"], str) or not isinstance(decision["signal_type"], str):
        raise ProducerParityError(label + "_DECISION_TEXT_FIELDS_INVALID")
    signal_bar_ms = _strict_int(decision["signal_bar_ms"], label + "_SIGNAL_BAR_MS")
    emitted_at_ms = _strict_int(decision["emitted_at_ms"], label + "_EMITTED_AT_MS")
    side = _strict_int(decision["side"], label + "_SIDE")
    priority = _strict_int(decision["priority"], label + "_PRIORITY")
    if signal_bar_ms <= 0 or emitted_at_ms <= 0:
        raise ProducerParityError(label + "_DECISION_TIMESTAMP_NONPOSITIVE")
    if side not in {-1, 1}:
        raise ProducerParityError(label + "_DECISION_SIDE_INVALID")
    if priority != R6_SOURCE_PRIORITY[decision["source"]]:
        raise ProducerParityError(label + "_DECISION_PRIORITY_MISMATCH")
    for field in ("atr_usd", "stop_atr", "target_atr", "lot_size"):
        if _finite_float(decision[field], label + "_" + field.upper()) <= 0:
            raise ProducerParityError(label + "_DECISION_" + field.upper() + "_NONPOSITIVE")
    if not isinstance(decision["geometry_used"], str) or not decision["geometry_used"]:
        raise ProducerParityError(label + "_DECISION_GEOMETRY_INVALID")
    if decision["admitted"] is not True:
        raise ProducerParityError(label + "_DECISION_NOT_ADMITTED")
    return dict(decision)


def load_stream(path: Path, label: str) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        raise ProducerParityError(label + "_STREAM_UNREADABLE") from exc
    if not lines:
        raise ProducerParityError(label + "_STREAM_EMPTY")
    for line_no, line in enumerate(lines, 1):
        if not line.strip():
            raise ProducerParityError(f"{label}_STREAM_BLANK_LINE:{line_no}")
        try:
            obj = json.loads(line)
        except Exception as exc:
            raise ProducerParityError(f"{label}_STREAM_BAD_JSON:{line_no}") from exc
        if not isinstance(obj, dict):
            raise ProducerParityError(f"{label}_STREAM_RECORD_INVALID:{line_no}")
        unknown = set(obj) - _RECORD_FIELDS
        missing = _RECORD_FIELDS - set(obj)
        if unknown or missing:
            raise ProducerParityError(f"{label}_STREAM_RECORD_SCHEMA_MISMATCH:{line_no}")
        fixture_id = obj["fixture_id"]
        if not isinstance(fixture_id, str) or not fixture_id:
            raise ProducerParityError(f"{label}_FIXTURE_ID_INVALID:{line_no}")
        if fixture_id in rows:
            raise ProducerParityError(label + "_DUPLICATE_FIXTURE_ID:" + fixture_id)
        cutoff = _strict_int(obj["available_through_ms"], label + "_AVAILABLE_THROUGH_MS")
        if cutoff <= 0:
            raise ProducerParityError(label + "_AVAILABLE_THROUGH_NONPOSITIVE")
        rows[fixture_id] = {
            "fixture_id": fixture_id,
            "available_through_ms": cutoff,
            "decision": _validate_decision(obj["decision"], label + f"_LINE_{line_no}"),
        }
    return rows


def _equal_numeric(a: Any, b: Any) -> bool:
    try:
        av, bv = float(a), float(b)
    except Exception:
        return False
    return math.isfinite(av) and math.isfinite(bv) and abs(av - bv) <= 1e-12


def _validate_isolation(
    isolation_path: Path,
    *,
    reference_path: Path,
    producer_path: Path,
    fixture_count: int,
) -> Dict[str, Any]:
    data = _load_json(isolation_path, "PARITY_ISOLATION")
    if data.get("schema") != ISOLATION_SCHEMA:
        raise ProducerParityError("PARITY_ISOLATION_SCHEMA_MISMATCH")
    if data.get("canonical_parent_zip_sha256") != CANONICAL_R6_ZIP_SHA256:
        raise ProducerParityError("PARITY_ISOLATION_PARENT_SHA_MISMATCH")
    if data.get("reference_stream_sha256") != sha256_file(reference_path):
        raise ProducerParityError("PARITY_ISOLATION_REFERENCE_HASH_MISMATCH")
    if data.get("producer_stream_sha256") != sha256_file(producer_path):
        raise ProducerParityError("PARITY_ISOLATION_PRODUCER_HASH_MISMATCH")
    if _strict_int(data.get("fixture_count"), "PARITY_ISOLATION_FIXTURE_COUNT") != fixture_count:
        raise ProducerParityError("PARITY_ISOLATION_FIXTURE_COUNT_MISMATCH")
    required_false = (
        "future_rows_available_to_producer",
        "outcome_columns_present",
        "final_holdout_accessed",
        "strategy_retuned",
    )
    for key in required_false:
        if data.get(key) is not False:
            raise ProducerParityError("PARITY_ISOLATION_GUARD_FAILED:" + key)
    if data.get("causal_prefix_fixture_generation") is not True:
        raise ProducerParityError("PARITY_ISOLATION_CAUSAL_PREFIX_NOT_PROVEN")
    return data


def build_parity_report(
    reference_path: Path,
    producer_stream_path: Path,
    *,
    isolation_path: Path,
    source_probe_path: Path,
    source_bundle_manifest_path: Path,
    producer_module_path: Path,
    producer_module_relative: str,
) -> Dict[str, Any]:
    reference_path = Path(reference_path).resolve()
    producer_stream_path = Path(producer_stream_path).resolve()
    source_probe_path = Path(source_probe_path).resolve()
    source_bundle_manifest_path = Path(source_bundle_manifest_path).resolve()
    producer_module_path = Path(producer_module_path).resolve()
    if not source_probe_path.is_file():
        raise ProducerParityError("SOURCE_PROBE_MISSING")
    if not source_bundle_manifest_path.is_file():
        raise ProducerParityError("SOURCE_BUNDLE_MANIFEST_MISSING")
    if not producer_module_path.is_file():
        raise ProducerParityError("PRODUCER_MODULE_MISSING")

    reference = load_stream(reference_path, "REFERENCE")
    producer = load_stream(producer_stream_path, "PRODUCER")
    if set(reference) != set(producer):
        missing = sorted(set(reference) - set(producer))
        extra = sorted(set(producer) - set(reference))
        raise ProducerParityError(
            "PARITY_FIXTURE_SET_MISMATCH:missing=" + ",".join(missing) + ";extra=" + ",".join(extra)
        )
    fixture_ids = sorted(reference)
    _validate_isolation(
        isolation_path,
        reference_path=reference_path,
        producer_path=producer_stream_path,
        fixture_count=len(fixture_ids),
    )

    mismatch_count = 0
    lookahead_violations = 0
    retired_source_emissions = 0
    source_coverage: Set[str] = set()
    selection_ok = True
    priority_ok = True
    geometry_ok = True
    lot_ok = True
    timestamp_ok = True
    mismatch_examples: List[Dict[str, Any]] = []

    for fixture_id in fixture_ids:
        ref = reference[fixture_id]
        prod = producer[fixture_id]
        fixture_mismatch: List[str] = []
        if ref["available_through_ms"] != prod["available_through_ms"]:
            fixture_mismatch.append("AVAILABLE_THROUGH_MISMATCH")
            timestamp_ok = False
        cutoff = min(ref["available_through_ms"], prod["available_through_ms"])
        rd, pd = ref["decision"], prod["decision"]
        if (rd is None) != (pd is None):
            fixture_mismatch.append("DECISION_PRESENCE_MISMATCH")
            selection_ok = False
        elif rd is not None and pd is not None:
            for field in _SELECTION_FIELDS:
                if rd[field] != pd[field]:
                    fixture_mismatch.append("SELECTION:" + field)
                    selection_ok = False
            for field in _GEOMETRY_FIELDS:
                equal = _equal_numeric(rd[field], pd[field]) if field != "geometry_used" else rd[field] == pd[field]
                if not equal:
                    fixture_mismatch.append("GEOMETRY:" + field)
                    geometry_ok = False
            if not _equal_numeric(rd["lot_size"], pd["lot_size"]):
                fixture_mismatch.append("LOT_SIZE_MISMATCH")
                lot_ok = False
            if rd["priority"] != R6_SOURCE_PRIORITY.get(rd["source"]) or pd["priority"] != R6_SOURCE_PRIORITY.get(pd["source"]):
                fixture_mismatch.append("SOURCE_PRIORITY_INVALID")
                priority_ok = False
            for label, decision in (("REFERENCE", rd), ("PRODUCER", pd)):
                if decision["signal_bar_ms"] > cutoff:
                    lookahead_violations += 1
                    fixture_mismatch.append(label + "_SIGNAL_AFTER_PREFIX")
                    timestamp_ok = False
                if decision["emitted_at_ms"] < decision["signal_bar_ms"]:
                    fixture_mismatch.append(label + "_EMITTED_BEFORE_SIGNAL")
                    timestamp_ok = False
            source_coverage.add(pd["source"])
            if pd["source"] == RETIRED_SOURCE:
                retired_source_emissions += 1
                fixture_mismatch.append("RETIRED_SOURCE_EMISSION")
        if fixture_mismatch:
            mismatch_count += 1
            if len(mismatch_examples) < 20:
                mismatch_examples.append({"fixture_id": fixture_id, "reasons": sorted(set(fixture_mismatch))})

    parity_pass = (
        mismatch_count == 0
        and lookahead_violations == 0
        and retired_source_emissions == 0
        and selection_ok and priority_ok and geometry_ok and lot_ok and timestamp_ok
    )
    return {
        "schema": PARITY_SCHEMA,
        "parity_tool_version": PARITY_TOOL_VERSION,
        "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
        "source_probe_sha256": sha256_file(source_probe_path),
        "source_bundle_manifest_sha256": sha256_file(source_bundle_manifest_path),
        "producer_module": producer_module_relative.replace("\\", "/"),
        "producer_module_sha256": sha256_file(producer_module_path),
        "reference_stream_sha256": sha256_file(reference_path),
        "producer_stream_sha256": sha256_file(producer_stream_path),
        "isolation_manifest_sha256": sha256_file(isolation_path),
        "parity_pass": parity_pass,
        "causal_prefix_only": lookahead_violations == 0,
        "signal_selection_parity": selection_ok,
        "source_priority_parity": priority_ok,
        "geometry_parity": geometry_ok,
        "lot_parity": lot_ok,
        "timestamp_causality_parity": timestamp_ok,
        "future_rows_read": False,
        "outcome_columns_read": False,
        "final_holdout_accessed": False,
        "strategy_retuned": False,
        "fixture_count": len(fixture_ids),
        "compared_decisions": sum(1 for x in producer.values() if x["decision"] is not None),
        "mismatch_count": mismatch_count,
        "lookahead_violations": lookahead_violations,
        "retired_source_emissions": retired_source_emissions,
        "frozen_sources_covered": sorted(source_coverage),
        "mismatch_examples": mismatch_examples,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build hash-bound causal R6 producer parity evidence")
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--producer-stream", type=Path, required=True)
    parser.add_argument("--isolation", type=Path, required=True)
    parser.add_argument("--source-probe", type=Path, required=True)
    parser.add_argument("--source-bundle-manifest", type=Path, required=True)
    parser.add_argument("--producer-module", type=Path, required=True)
    parser.add_argument("--producer-relative", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_parity_report(
        args.reference,
        args.producer_stream,
        isolation_path=args.isolation,
        source_probe_path=args.source_probe,
        source_bundle_manifest_path=args.source_bundle_manifest,
        producer_module_path=args.producer_module,
        producer_module_relative=args.producer_relative,
    )
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not report["parity_pass"]:
        raise SystemExit(2)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
