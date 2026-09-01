from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional, Tuple

from .constants import CANONICAL_R6_ZIP_SHA256, RETIRED_SOURCE, R6_SOURCE_PRIORITY
from .r6_integrity import sha256_file
from .r6_producer_replay import ProducerReplayError, verify_replay_evidence
from .r6_source_bundle import BUNDLE_VERSION, OWNERSHIP_MARKER_NAME
from .r6_source_probe import PROBE_VERSION


class ProducerAdmissionError(RuntimeError):
    pass


ADMISSION_VERSION = "R7_R1_R6_PRODUCER_ADMISSION_V4"
PARITY_SCHEMA = "V16_R6_CAUSAL_PRODUCER_PARITY_V1"
EXPECTED_PARITY_TOOL_VERSION = "R7_R1_R6_PRODUCER_PARITY_TOOL_V3"
EXPECTED_ISOLATION_SCHEMA = "V16_R6_CAUSAL_FIXTURE_ISOLATION_V2"
PRODUCER_MODULE_RELATIVE = "r7_runtime/r6_causal_producer.py"
_PROHIBITED_SOURCE_PATH_TOKENS = (
    "final_holdout",
    "research_consumed_validation",
    "protected_validation",
    "retrospective_research",
    "validation_result",
)

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


def _validate_sha256_text(value: Any, error: str) -> str:
    digest = str(value or "").lower()
    if len(digest) != 64:
        raise ProducerAdmissionError(error)
    try:
        int(digest, 16)
    except ValueError as exc:
        raise ProducerAdmissionError(error) from exc
    return digest


def _require_file_hash(path: Path, expected: Any, error: str) -> str:
    path = Path(path)
    if not path.is_file():
        raise ProducerAdmissionError(error + "_FILE_MISSING")
    digest = _validate_sha256_text(expected, error + "_HASH_INVALID")
    if sha256_file(path) != digest:
        raise ProducerAdmissionError(error + "_HASH_MISMATCH")
    return digest


def _normalized_hash_map(data: Any, label: str) -> Dict[str, str]:
    if not isinstance(data, dict):
        raise ProducerAdmissionError(label + "_MISSING")
    out: Dict[str, str] = {}
    for key, value in data.items():
        relative = str(key).replace("\\", "/")
        if relative in out:
            raise ProducerAdmissionError(label + "_DUPLICATE_NORMALIZED_PATH:" + relative)
        out[relative] = _validate_sha256_text(value, label + "_INVALID_HASH:" + relative)
    return out


def _parent_source_hashes(parent_manifest: Dict[str, Any]) -> Dict[str, str]:
    protected = _normalized_hash_map(parent_manifest.get("protected_r6_hashes"), "PARENT_PROTECTED_HASHES")
    out: Dict[str, str] = {}
    for relative in REQUIRED_SOURCE_FILES:
        digest = protected.get(relative)
        if digest is None:
            raise ProducerAdmissionError("PARENT_SOURCE_HASH_RESOLUTION_FAILED:" + relative)
        out[relative] = digest
    return out


def _validate_source_relative(relative: str) -> str:
    normalized = str(relative).replace("\\", "/")
    pure = PurePosixPath(normalized)
    if (
        not normalized
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or (pure.parts and ":" in pure.parts[0])
    ):
        raise ProducerAdmissionError("SOURCE_BUNDLE_PATH_INVALID:" + normalized)
    if not normalized.lower().endswith(".py"):
        raise ProducerAdmissionError("SOURCE_BUNDLE_NON_PYTHON_FILE:" + normalized)
    lowered = normalized.lower()
    if any(token in lowered for token in _PROHIBITED_SOURCE_PATH_TOKENS):
        raise ProducerAdmissionError("SOURCE_BUNDLE_PROHIBITED_PATH:" + normalized)
    return normalized


def verify_source_bundle(
    root: Path,
    *,
    parent_manifest_path: Path,
    source_probe_path: Path,
    source_bundle_manifest_path: Path,
) -> Dict[str, Any]:
    root = Path(root).resolve()
    parent = _load_json(parent_manifest_path, "PARENT_MANIFEST")
    bundle = _load_json(source_bundle_manifest_path, "SOURCE_BUNDLE_MANIFEST")

    if parent.get("canonical_parent_zip_sha256") != CANONICAL_R6_ZIP_SHA256:
        raise ProducerAdmissionError("PARENT_CANONICAL_SHA_MISMATCH")
    if parent.get("build_verified_parent_zip_sha256") != CANONICAL_R6_ZIP_SHA256:
        raise ProducerAdmissionError("PARENT_BUILD_SHA_MISMATCH")
    if bundle.get("bundle_version") != BUNDLE_VERSION:
        raise ProducerAdmissionError("SOURCE_BUNDLE_VERSION_MISMATCH")
    if bundle.get("canonical_parent_zip_sha256") != CANONICAL_R6_ZIP_SHA256:
        raise ProducerAdmissionError("SOURCE_BUNDLE_PARENT_SHA_MISMATCH")
    _require_true(bundle, "source_only_bundle", "SOURCE_BUNDLE_NOT_SOURCE_ONLY")
    _require_true(
        bundle,
        "static_local_python_dependency_closure_extracted",
        "SOURCE_BUNDLE_DEPENDENCY_CLOSURE_NOT_PROVEN",
    )
    _require_true(bundle, "required_local_imports_resolved", "SOURCE_BUNDLE_LOCAL_IMPORTS_UNRESOLVED")
    _require_false(bundle, "dynamic_imports_allowed", "SOURCE_BUNDLE_DYNAMIC_IMPORTS_ALLOWED")
    _require_false(bundle, "prohibited_source_paths_allowed", "SOURCE_BUNDLE_PROHIBITED_PATHS_ALLOWED")
    _require_true(bundle, "owned_output_replacement_only", "SOURCE_BUNDLE_OUTPUT_OWNERSHIP_NOT_PROVEN")
    _require_false(bundle, "strategy_executed", "SOURCE_BUNDLE_EXECUTED_STRATEGY")
    _require_false(bundle, "strategy_retuned", "SOURCE_BUNDLE_RETUNED_STRATEGY")
    _require_false(bundle, "final_holdout_accessed", "SOURCE_BUNDLE_HOLDOUT_BOUNDARY_BREACH")
    _require_false(bundle, "producer_admitted", "SOURCE_BUNDLE_SELF_ADMISSION_FORBIDDEN")

    ownership_marker_file = bundle.get("ownership_marker_file")
    if ownership_marker_file != OWNERSHIP_MARKER_NAME:
        raise ProducerAdmissionError("SOURCE_BUNDLE_OWNERSHIP_MARKER_NAME_MISMATCH")
    ownership_marker_sha256 = _validate_sha256_text(
        bundle.get("ownership_marker_sha256"),
        "SOURCE_BUNDLE_OWNERSHIP_MARKER_HASH_INVALID",
    )

    if bundle.get("source_probe_file") != Path(source_probe_path).name:
        raise ProducerAdmissionError("SOURCE_BUNDLE_PROBE_FILENAME_MISMATCH")
    if bundle.get("source_probe_sha256") != sha256_file(source_probe_path):
        raise ProducerAdmissionError("SOURCE_BUNDLE_PROBE_HASH_MISMATCH")

    dependency_count = _strict_nonnegative_int(bundle.get("dependency_count"), "SOURCE_BUNDLE_DEPENDENCY_COUNT")
    closure = bundle.get("dependency_closure_files")
    files = bundle.get("files")
    required = bundle.get("required_source_files")
    if not isinstance(closure, list) or any(not isinstance(x, str) for x in closure):
        raise ProducerAdmissionError("SOURCE_BUNDLE_DEPENDENCY_CLOSURE_INVALID")
    if not isinstance(files, dict):
        raise ProducerAdmissionError("SOURCE_BUNDLE_FILES_INVALID")
    if not isinstance(required, list) or any(not isinstance(x, str) for x in required):
        raise ProducerAdmissionError("SOURCE_BUNDLE_REQUIRED_FILES_INVALID")
    normalized_closure = [_validate_source_relative(x) for x in closure]
    if len(set(normalized_closure)) != len(normalized_closure):
        raise ProducerAdmissionError("SOURCE_BUNDLE_DUPLICATE_DEPENDENCY_PATH")
    normalized_files = {_validate_source_relative(k): v for k, v in files.items()}
    if dependency_count <= 0 or dependency_count != len(normalized_closure) or dependency_count != len(normalized_files):
        raise ProducerAdmissionError("SOURCE_BUNDLE_DEPENDENCY_COUNT_MISMATCH")
    if set(normalized_closure) != set(normalized_files):
        raise ProducerAdmissionError("SOURCE_BUNDLE_DEPENDENCY_FILESET_MISMATCH")
    normalized_required = {_validate_source_relative(x) for x in required}
    if normalized_required != set(REQUIRED_SOURCE_FILES):
        raise ProducerAdmissionError("SOURCE_BUNDLE_REQUIRED_ENTRY_SET_MISMATCH")
    if not normalized_required.issubset(set(normalized_closure)):
        raise ProducerAdmissionError("SOURCE_BUNDLE_REQUIRED_ENTRY_MISSING_FROM_CLOSURE")

    parent_tree = _normalized_hash_map(parent.get("parent_tree_sha256"), "PARENT_TREE_HASHES")
    verified_files: Dict[str, str] = {}
    for relative in normalized_closure:
        entry = normalized_files[relative]
        if not isinstance(entry, dict):
            raise ProducerAdmissionError("SOURCE_BUNDLE_FILE_ENTRY_INVALID:" + relative)
        digest = _validate_sha256_text(entry.get("sha256"), "SOURCE_BUNDLE_FILE_HASH_INVALID:" + relative)
        size = _strict_nonnegative_int(entry.get("size_bytes"), "SOURCE_BUNDLE_FILE_SIZE:" + relative)
        actual = (root / relative).resolve()
        try:
            actual.relative_to(root)
        except ValueError as exc:
            raise ProducerAdmissionError("SOURCE_BUNDLE_FILE_PATH_ESCAPE:" + relative) from exc
        if not actual.is_file():
            raise ProducerAdmissionError("SOURCE_BUNDLE_FILE_MISSING:" + relative)
        if actual.stat().st_size != size:
            raise ProducerAdmissionError("SOURCE_BUNDLE_FILE_SIZE_MISMATCH:" + relative)
        actual_hash = sha256_file(actual)
        if actual_hash != digest:
            raise ProducerAdmissionError("SOURCE_BUNDLE_FILE_HASH_MISMATCH:" + relative)
        if parent_tree.get(relative) != digest:
            raise ProducerAdmissionError("SOURCE_BUNDLE_NOT_CANONICAL_PARENT_BYTES:" + relative)
        verified_files[relative] = digest

    unresolved = bundle.get("unresolved_nonarchive_imports")
    if not isinstance(unresolved, dict):
        raise ProducerAdmissionError("SOURCE_BUNDLE_EXTERNAL_IMPORTS_INVALID")
    for relative, imports in unresolved.items():
        normalized = _validate_source_relative(relative)
        if normalized not in verified_files:
            raise ProducerAdmissionError("SOURCE_BUNDLE_EXTERNAL_IMPORT_SOURCE_UNKNOWN:" + normalized)
        if not isinstance(imports, list) or any(not isinstance(x, str) or not x for x in imports):
            raise ProducerAdmissionError("SOURCE_BUNDLE_EXTERNAL_IMPORT_LIST_INVALID:" + normalized)

    return {
        "bundle_version": BUNDLE_VERSION,
        "manifest_sha256": sha256_file(source_bundle_manifest_path),
        "dependency_count": dependency_count,
        "verified_files": verified_files,
        "unresolved_nonarchive_imports": unresolved,
        "prohibited_source_paths_blocked": True,
        "owned_output_replacement_only": True,
        "ownership_marker_file": OWNERSHIP_MARKER_NAME,
        "ownership_marker_sha256": ownership_marker_sha256,
    }


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
    _require_true(probe, "normalized_ast_source_included", "SOURCE_PROBE_IMPLEMENTATION_MAP_MISSING")
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
    source_bundle_manifest_path: Path,
    fixture_path: Path,
    replay_attestation_path: Path,
    parity_path: Path,
    reference_stream_path: Path,
    producer_stream_path: Path,
    isolation_path: Path,
) -> Dict[str, Any]:
    root = Path(root).resolve()
    parity = _load_json(parity_path, "PRODUCER_PARITY")
    if parity.get("schema") != PARITY_SCHEMA:
        raise ProducerAdmissionError("PRODUCER_PARITY_SCHEMA_MISMATCH")
    if parity.get("parity_tool_version") != EXPECTED_PARITY_TOOL_VERSION:
        raise ProducerAdmissionError("PRODUCER_PARITY_TOOL_VERSION_MISMATCH")
    if parity.get("canonical_parent_zip_sha256") != CANONICAL_R6_ZIP_SHA256:
        raise ProducerAdmissionError("PRODUCER_PARITY_PARENT_SHA_MISMATCH")
    if parity.get("source_probe_sha256") != sha256_file(source_probe_path):
        raise ProducerAdmissionError("PRODUCER_PARITY_SOURCE_PROBE_HASH_MISMATCH")
    if parity.get("source_bundle_manifest_sha256") != sha256_file(source_bundle_manifest_path):
        raise ProducerAdmissionError("PRODUCER_PARITY_SOURCE_BUNDLE_HASH_MISMATCH")
    if parity.get("fixture_corpus_sha256") != sha256_file(fixture_path):
        raise ProducerAdmissionError("PRODUCER_PARITY_FIXTURE_HASH_MISMATCH")
    if parity.get("producer_replay_attestation_sha256") != sha256_file(replay_attestation_path):
        raise ProducerAdmissionError("PRODUCER_PARITY_REPLAY_HASH_MISMATCH")

    reference_hash = _require_file_hash(
        reference_stream_path, parity.get("reference_stream_sha256"), "PRODUCER_PARITY_REFERENCE_STREAM"
    )
    producer_stream_hash = _require_file_hash(
        producer_stream_path, parity.get("producer_stream_sha256"), "PRODUCER_PARITY_PRODUCER_STREAM"
    )
    isolation_hash = _require_file_hash(
        isolation_path, parity.get("isolation_manifest_sha256"), "PRODUCER_PARITY_ISOLATION"
    )

    isolation = _load_json(isolation_path, "PRODUCER_PARITY_ISOLATION")
    if isolation.get("schema") != EXPECTED_ISOLATION_SCHEMA:
        raise ProducerAdmissionError("PRODUCER_PARITY_ISOLATION_SCHEMA_MISMATCH")
    if isolation.get("canonical_parent_zip_sha256") != CANONICAL_R6_ZIP_SHA256:
        raise ProducerAdmissionError("PRODUCER_PARITY_ISOLATION_PARENT_SHA_MISMATCH")
    if isolation.get("reference_stream_sha256") != reference_hash:
        raise ProducerAdmissionError("PRODUCER_PARITY_ISOLATION_REFERENCE_HASH_MISMATCH")
    if isolation.get("producer_stream_sha256") != producer_stream_hash:
        raise ProducerAdmissionError("PRODUCER_PARITY_ISOLATION_PRODUCER_HASH_MISMATCH")
    if isolation.get("fixture_corpus_sha256") != sha256_file(fixture_path):
        raise ProducerAdmissionError("PRODUCER_PARITY_ISOLATION_FIXTURE_HASH_MISMATCH")
    if isolation.get("producer_replay_attestation_sha256") != sha256_file(replay_attestation_path):
        raise ProducerAdmissionError("PRODUCER_PARITY_ISOLATION_REPLAY_HASH_MISMATCH")
    _require_true(isolation, "causal_prefix_fixture_generation", "PRODUCER_PARITY_ISOLATION_NOT_CAUSAL_PREFIX")
    _require_true(isolation, "trusted_producer_replay", "PRODUCER_PARITY_ISOLATION_TRUSTED_REPLAY_MISSING")
    _require_true(isolation, "producer_source_policy_pass", "PRODUCER_PARITY_ISOLATION_SOURCE_POLICY_MISSING")
    _require_false(isolation, "future_rows_available_to_producer", "PRODUCER_PARITY_ISOLATION_FUTURE_ROWS_AVAILABLE")
    _require_false(isolation, "outcome_columns_present", "PRODUCER_PARITY_ISOLATION_OUTCOMES_PRESENT")
    _require_false(isolation, "final_holdout_accessed", "PRODUCER_PARITY_ISOLATION_HOLDOUT_BOUNDARY_BREACH")
    _require_false(isolation, "strategy_retuned", "PRODUCER_PARITY_ISOLATION_RETUNING_BREACH")

    producer_rel = str(parity.get("producer_module", "")).replace("\\", "/")
    if producer_rel != PRODUCER_MODULE_RELATIVE:
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

    _require_true(parity, "trusted_producer_replay_pass", "PRODUCER_TRUSTED_REPLAY_NOT_PASS")
    _require_true(parity, "producer_source_policy_pass", "PRODUCER_SOURCE_POLICY_NOT_PASS")
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
    isolation_fixtures = _strict_nonnegative_int(isolation.get("fixture_count"), "PRODUCER_PARITY_ISOLATION_FIXTURE_COUNT")
    if fixtures != isolation_fixtures:
        raise ProducerAdmissionError("PRODUCER_PARITY_ISOLATION_FIXTURE_COUNT_MISMATCH")
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
        "source_bundle_manifest_sha256": sha256_file(source_bundle_manifest_path),
        "fixture_corpus_sha256": sha256_file(fixture_path),
        "producer_replay_attestation_sha256": sha256_file(replay_attestation_path),
        "reference_stream_sha256": reference_hash,
        "producer_stream_sha256": producer_stream_hash,
        "isolation_manifest_sha256": isolation_hash,
        "fixture_count": fixtures,
        "compared_decisions": compared,
        "frozen_sources_covered": sorted(covered_set),
        "trusted_producer_replay_pass": True,
        "producer_source_policy_pass": True,
        "parity_pass": True,
    }


def verify_producer_admission(
    root: Path,
    *,
    parent_manifest_path: Optional[Path] = None,
    source_probe_path: Optional[Path] = None,
    source_bundle_manifest_path: Optional[Path] = None,
    fixture_path: Optional[Path] = None,
    replay_attestation_path: Optional[Path] = None,
    parity_path: Optional[Path] = None,
    reference_stream_path: Optional[Path] = None,
    producer_stream_path: Optional[Path] = None,
    isolation_path: Optional[Path] = None,
    producer_module_path: Optional[Path] = None,
) -> Dict[str, Any]:
    root = Path(root).resolve()
    parent_manifest_path = parent_manifest_path or root / "R7_R1_PARENT_INTEGRITY.json"
    source_probe_path = source_probe_path or root / "R7_R1_R6_SOURCE_PROBE.json"
    source_bundle_manifest_path = source_bundle_manifest_path or root / "R7_R1_R6_SOURCE_BUNDLE_MANIFEST.json"
    fixture_path = fixture_path or root / "R7_R1_R6_PARITY_FIXTURES.jsonl"
    replay_attestation_path = replay_attestation_path or root / "R7_R1_R6_PRODUCER_REPLAY.json"
    parity_path = parity_path or root / "R7_R1_R6_PRODUCER_PARITY.json"
    reference_stream_path = reference_stream_path or root / "R7_R1_R6_REFERENCE_STREAM.jsonl"
    producer_stream_path = producer_stream_path or root / "R7_R1_R6_PRODUCER_STREAM.jsonl"
    isolation_path = isolation_path or root / "R7_R1_R6_PARITY_ISOLATION.json"
    producer_module_path = producer_module_path or root / PRODUCER_MODULE_RELATIVE

    bundle = verify_source_bundle(
        root,
        parent_manifest_path=parent_manifest_path,
        source_probe_path=source_probe_path,
        source_bundle_manifest_path=source_bundle_manifest_path,
    )
    source_hashes = verify_source_probe(
        root,
        parent_manifest_path=parent_manifest_path,
        source_probe_path=source_probe_path,
    )
    try:
        replay = verify_replay_evidence(
            fixture_path,
            producer_module_path,
            producer_stream_path,
            replay_attestation_path,
        )
    except ProducerReplayError as exc:
        raise ProducerAdmissionError("PRODUCER_TRUSTED_REPLAY_FAILED:" + str(exc)) from exc
    parity = verify_parity_evidence(
        root,
        source_probe_path=source_probe_path,
        source_bundle_manifest_path=source_bundle_manifest_path,
        fixture_path=fixture_path,
        replay_attestation_path=replay_attestation_path,
        parity_path=parity_path,
        reference_stream_path=reference_stream_path,
        producer_stream_path=producer_stream_path,
        isolation_path=isolation_path,
    )
    return {
        "admission_version": ADMISSION_VERSION,
        "ready": True,
        "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
        "source_bundle": bundle,
        "source_hashes": source_hashes,
        "trusted_replay": replay,
        "parity": parity,
        "final_holdout_accessed": False,
        "strategy_retuned": False,
    }


def producer_admission_status(root: Path) -> Dict[str, Any]:
    try:
        return verify_producer_admission(root)
    except Exception as exc:
        return {
            "admission_version": ADMISSION_VERSION,
            "ready": False,
            "reason": str(exc),
            "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
            "final_holdout_accessed": False,
            "strategy_retuned": False,
        }
