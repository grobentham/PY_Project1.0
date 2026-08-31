from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

from .constants import CANONICAL_R6_ZIP_SHA256, RETIRED_SOURCE, R6_SOURCE_PRIORITY
from .r6_integrity import sha256_file
from .r6_source_probe import PROBE_VERSION


class ProducerAdmissionError(RuntimeError):
    pass


ADMISSION_VERSION = "R7_R1_R6_PRODUCER_ADMISSION_V1"
PARITY_SCHEMA = "V16_R6_CAUSAL_PRODUCER_PARITY_V1"

REQUIRED_SOURCE_FILES: Tuple[str, ...] = (
    "v16r6/engine.py",
    "v16r5/engine.py",
    "V16_R5_MAIN.py",
)

REQUIRED_FROZEN_SOURCES = frozenset(R6_SOURCE_PRIORITY)


def _load_json(path: Path, label: str) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise ProducerAdmissionError(f"{label}_UNREADABLE:{exc}") from exc
    if not isinstance(data, dict):
        raise ProducerAdmissionError(f"{label}_INVALID")
    return data


def _strict_nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProducerAdmissionError(name + "_INVALID")
    return int(value)


def _require_true(data: Dict[str, Any], key: str, error: str) -> None:
    if data.get(key) is not True:
        raise ProducerAdmissionError(error)


def _require_false(data: Dict[str, Any], key: str, error: str) -> None:
    if data.get(key) is not False:
        raise ProducerAdmissionError(error)


def _parent_source_hashes(parent_manifest: Dict[str, Any]) -> Dict[str, str]:
    protected = parent_manifest.get("protected_r6_hashes")
    if not isinstance(protected, dict):
        raise ProducerAdmissionError("PARENT_PROTECTED_HASHES_MISSING")
    out: Dict[str, str] = {}
    for relative in REQUIRED_SOURCE_FILES:
        matches = [str(v) for k, v in protected.items() if str(k).replace("\\", "/") == relative]
        if len(matches) != 1:
            raise ProducerAdmissionError(f"PARENT_SOURCE_HASH_RESOLUTION_FAILED:{relative}:matches={len(matches)}")
        digest = matches[0].lower()
        if len(digest) != 64:
            raise ProducerAdmissionError(f"PARENT_SOURCE_HASH_INVALID:{relative}")
        out[relative] = digest
    return out


def verify_source_probe(root: Path, *, parent_manifest_path: Path, source_probe_path: Path) -> Dict[str, str]:
    root = Path(root).resolve()
    parent = _load_json(parent_manifest_path, "PARENT_MANIFEST")
    probe = _load_json(source_probe_path, "SOURCE_PROBE")

    if parent.get("canonical_parent_zip_sha256") != CANONICAL_R6_ZIP_SHA256:
        raise ProducerAdmissionError("PARENT_CANONICAL_SHA_MISMATCH")
    if parent.get("build_verified_parent_zip_sha256") != CANONICAL_R6_ZIP_SHA256:
        raise ProducerAdmissionError("PARENT_BUILD_SHA_MISMATCH")
    if probe.get("probe_version") != PROBE_VERSION:
        raise ProducerAdmissionError("SOURCE_PROBE_VERSION_MISMATCH")
    if probe.get("canonical_parent_zip_sha256") != CANONICAL_R6_ZIP_SHA256:
        raise ProducerAdmissionError("SOURCE_PROBE_PARENT_SHA_MISMATCH")
    _require_true(probe, "source_only_probe", "SOURCE_PROBE_NOT_SOURCE_ONLY")
    _require_true(probe, "required_engine_contract_present", "SOURCE_PROBE_ENGINE_CONTRACT_MISSING")
    _require_false(probe, "final_holdout_accessed", "SOURCE_PROBE_HOLDOUT_BOUNDARY_BREACH")
    _require_false(probe, "strategy_executed", "SOURCE_PROBE_EXECUTED_STRATEGY")
    _require_false(probe, "strategy_retuned", "SOURCE_PROBE_RETUNED_STRATEGY")
    _require_false(probe, "producer_admitted", "SOURCE_PROBE_SELF_ADMISSION_FORBIDDEN")

    files = probe.get("files")
    if not isinstance(files, dict):
        raise ProducerAdmissionError("SOURCE_PROBE_FILES_MISSING")
    parent_hashes = _parent_source_hashes(parent)
    verified: Dict[str, str] = {}
    for relative in REQUIRED_SOURCE_FILES:
        entry = files.get(relative)
        if not isinstance(entry, dict):
            raise ProducerAdmissionError(f"SOURCE_PROBE_FILE_MISSING:{relative}")
        digest = str(entry.get("sha256", "")).lower()
        if digest != parent_hashes[relative]:
            raise ProducerAdmissionError(f"SOURCE_PROBE_HASH_MISMATCH:{relative}")
        actual = root / relative
        if not actual.is_file() or sha256_file(actual) != digest:
            raise ProducerAdmissionError(f"SOURCE_FILE_HASH_MISMATCH:{relative}")
        verified[relative] = digest
    return verified


def verify_parity_evidence(
    root: Path,
    *,
    source_probe_path: Path,
    parity_path: Path,
) -> Dict[str, Any]:
    root = Path(root).resolve()
    parity = _load_json(parity_path, "PRODUCER_PARITY")
    if parity.get("schema") != PARITY_SCHEMA:
        raise ProducerAdmissionError("PRODUCER_PARITY_SCHEMA_MISMATCH")
    if parity.get("canonical_parent_zip_sha256") != CANONICAL_R6_ZIP_SHA256:
        raise ProducerAdmissionError("PRODUCER_PARITY_PARENT_SHA_MISMATCH")
    if parity.get("source_probe_sha256") != sha256_file(source_probe_path):
        raise ProducerAdmissionError("PRODUCER_PARITY_SOURCE_PROBE_HASH_MISMATCH")

    producer_rel = str(parity.get("producer_module", "")).replace("\\", "/")
    if not producer_rel or producer_rel.startswith("/") or ".." in Path(producer_rel).parts:
        raise ProducerAdmissionError("PRODUCER_MODULE_PATH_INVALID")
    producer_path = (root / producer_rel).resolve()
    try:
        producer_path.relative_to(root)
    except ValueError as exc:
        raise ProducerAdmissionError("PRODUCER_MODULE_PATH_ESCAPE") from exc
    if not producer_path.is_file():
        raise ProducerAdmissionError("PRODUCER_MODULE_MISSING")
    expected_producer_hash = str(parity.get("producer_module_sha256", "")).lower()
    if len(expected_producer_hash) != 64 or sha256_file(producer_path) != expected_producer_hash:
        raise ProducerAdmissionError("PRODUCER_MODULE_HASH_MISMATCH")

    _require_true(parity, "parity_pass", "PRODUCER_PARITY_NOT_PASS")
    _require_true(parity, "causal_prefix_only", "PRODUCER_PARITY_NOT_CAUSAL_PREFIX_ONLY")
    _require_true(parity, "signal_selection_parity", "PRODUCER_SIGNAL_SELECTION_PARITY_MISSING")
    _require_true(parity, "source_priority_parity", "PRODUCER_SOURCE_PRIORITY_PARITY_MISSING")
    _require_true(parity, "geometry_parity", "PRODUCER_GEOMETRY_PARITY_MISSING")
    _require_true(parity, "lot_parity", "PRODUCER_LOT_PARITY_MISSING")
    _require_true(parity, "timestamp_causality_parity", "PRODUCER_TIMESTAMP_CAUSALITY_PARITY_MISSING")
    _require_false(parity, "future_rows_read", "PRODUCER_PARITY_FUTURE_ROW_READ")
    _require_false(parity, "outcome_columns_read", "PRODUCER_PARITY_OUTCOME_COLUMN_READ")
    _require_false(parity, "final_holdout_accessed", "PRODUCER_PARITY_HOLDOUT_BOUNDARY_BREACH")
    _require_false(parity, "strategy_retuned", "PRODUCER_PARITY_RETUNING_BREACH")

    fixtures = _strict_nonnegative_int(parity.get("fixture_count"), "PRODUCER_PARITY_FIXTURE_COUNT")
    compared = _strict_nonnegative_int(parity.get("compared_decisions"), "PRODUCER_PARITY_COMPARED_DECISIONS")
    mismatches = _strict_nonnegative_int(parity.get("mismatch_count"), "PRODUCER_PARITY_MISMATCH_COUNT")
    lookahead = _strict_nonnegative_int(parity.get("lookahead_violations"), "PRODUCER_PARITY_LOOKAHEAD_VIOLATIONS")
    retired = _strict_nonnegative_int(parity.get("retired_source_emissions"), "PRODUCER_PARITY_RETIRED_SOURCE_EMISSIONS")
    if fixtures <= 0 or compared <= 0:
        raise ProducerAdmissionError("PRODUCER_PARITY_EVIDENCE_EMPTY")
    if mismatches != 0:
        raise ProducerAdmissionError("PRODUCER_PARITY_MISMATCHES_PRESENT")
    if lookahead != 0:
        raise ProducerAdmissionError("PRODUCER_PARITY_LOOKAHEAD_VIOLATION")
    if retired != 0:
        raise ProducerAdmissionError("PRODUCER_PARITY_RETIRED_SOURCE_EMISSION")

    covered = parity.get("frozen_sources_covered")
    if not isinstance(covered, list) or any(not isinstance(x, str) for x in covered):
        raise ProducerAdmissionError("PRODUCER_PARITY_SOURCE_COVERAGE_INVALID")
    covered_set = set(covered)
    if RETIRED_SOURCE in covered_set:
        raise ProducerAdmissionError("PRODUCER_PARITY_RETIRED_SOURCE_MARKED_COVERED")
    if covered_set != REQUIRED_FROZEN_SOURCES:
        missing = sorted(REQUIRED_FROZEN_SOURCES - covered_set)
        extra = sorted(covered_set - REQUIRED_FROZEN_SOURCES)
        raise ProducerAdmissionError(
            "PRODUCER_PARITY_SOURCE_COVERAGE_MISMATCH:missing=" + ",".join(missing) + ";extra=" + ",".join(extra)
        )

    return {
        "producer_module": producer_rel,
        "producer_module_sha256": expected_producer_hash,
        "fixture_count": fixtures,
        "compared_decisions": compared,
        "frozen_sources_covered": sorted(covered_set),
        "parity_pass": True,
    }


def verify_producer_admission(
    root: Path,
    *,
    parent_manifest_path: Path | None = None,
    source_probe_path: Path | None = None,
    parity_path: Path | None = None,
) -> Dict[str, Any]:
    root = Path(root).resolve()
    parent_manifest_path = parent_manifest_path or root / "R7_R1_PARENT_INTEGRITY.json"
    source_probe_path = source_probe_path or root / "R7_R1_R6_SOURCE_PROBE.json"
    parity_path = parity_path or root / "R7_R1_R6_PRODUCER_PARITY.json"

    source_hashes = verify_source_probe(
        root,
        parent_manifest_path=parent_manifest_path,
        source_probe_path=source_probe_path,
    )
    parity = verify_parity_evidence(root, source_probe_path=source_probe_path, parity_path=parity_path)
    return {
        "admission_version": ADMISSION_VERSION,
        "ready": True,
        "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
        "source_hashes": source_hashes,
        "parity": parity,
        "final_holdout_accessed": False,
        "strategy_retuned": False,
    }


def producer_admission_status(root: Path) -> Dict[str, Any]:
    try:
        result = verify_producer_admission(root)
        return result
    except Exception as exc:
        return {
            "admission_version": ADMISSION_VERSION,
            "ready": False,
            "reason": str(exc),
            "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
            "final_holdout_accessed": False,
            "strategy_retuned": False,
        }
