from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .constants import CANONICAL_R6_ZIP_SHA256
from .r6_integrity import sha256_file
from .r6_producer_admission import verify_producer_admission as verify_v4_candidate_admission
from .r6_producer_replay import (
    MAX_EXECUTION_LINE_EVENTS,
    MAX_FIXTURE_COUNT,
    MAX_INPUT_DEPTH,
    MAX_INPUT_NODES_PER_FIXTURE,
    MAX_RANGE_ITEMS,
    MAX_REPLAY_WALL_SECONDS,
    REPLAY_VERSION,
    SOURCE_POLICY_VERSION,
)
from .r6_reference_replay import (
    ReferenceExecutor,
    ReferenceReplayError,
    verify_reference_replay_evidence,
)
from .r6_source_bundle import BUNDLE_VERSION


class ProducerAdmissionAuthorityError(RuntimeError):
    pass


AUTHORITY_VERSION = "R7_R1_R6_PRODUCER_ADMISSION_AUTHORITY_V5"


def _verify_trusted_replay_security_contract(candidate: Dict[str, Any]) -> Dict[str, Any]:
    replay = candidate.get("trusted_replay")
    if not isinstance(replay, dict):
        raise ProducerAdmissionAuthorityError("TRUSTED_REPLAY_SECURITY_CONTRACT_MISSING")
    if replay.get("replay_version") != REPLAY_VERSION:
        raise ProducerAdmissionAuthorityError("TRUSTED_REPLAY_VERSION_MISMATCH")
    if replay.get("source_policy_version") != SOURCE_POLICY_VERSION:
        raise ProducerAdmissionAuthorityError("TRUSTED_REPLAY_SOURCE_POLICY_VERSION_MISMATCH")
    required_true = (
        "deterministic_double_run",
        "source_policy_pass",
        "range_is_bounded",
        "execution_line_budget_enforced",
        "process_isolation_enforced",
    )
    for key in required_true:
        if replay.get(key) is not True:
            raise ProducerAdmissionAuthorityError("TRUSTED_REPLAY_REQUIRED_GUARD_MISSING:" + key)
    required_false = (
        "imports_allowed",
        "classes_allowed",
        "while_loops_allowed",
        "exception_handling_allowed",
        "function_decorators_allowed",
        "function_annotations_allowed",
        "mutable_top_level_state_allowed",
        "mutable_or_executable_defaults_allowed",
        "dunder_access_allowed",
        "filesystem_api_allowed",
        "network_api_allowed",
        "dynamic_import_allowed",
        "future_rows_available_to_producer",
        "outcome_columns_present",
        "final_holdout_accessed",
        "strategy_retuned",
    )
    for key in required_false:
        if replay.get(key) is not False:
            raise ProducerAdmissionAuthorityError("TRUSTED_REPLAY_FORBIDDEN_GUARD_ENABLED:" + key)
    if replay.get("producer_input_mutation_count") != 0:
        raise ProducerAdmissionAuthorityError("TRUSTED_REPLAY_INPUT_MUTATION_PRESENT")
    exact_limits = {
        "max_fixture_count": MAX_FIXTURE_COUNT,
        "max_input_depth": MAX_INPUT_DEPTH,
        "max_input_nodes_per_fixture": MAX_INPUT_NODES_PER_FIXTURE,
        "max_range_items": MAX_RANGE_ITEMS,
        "max_execution_line_events": MAX_EXECUTION_LINE_EVENTS,
    }
    for key, expected in exact_limits.items():
        value = replay.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value != expected:
            raise ProducerAdmissionAuthorityError("TRUSTED_REPLAY_RESOURCE_LIMIT_MISMATCH:" + key)
    timeout = replay.get("wall_timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or float(timeout) != float(MAX_REPLAY_WALL_SECONDS):
        raise ProducerAdmissionAuthorityError("TRUSTED_REPLAY_WALL_TIMEOUT_MISMATCH")
    worker_hash = replay.get("worker_module_sha256")
    if not isinstance(worker_hash, str) or len(worker_hash) != 64:
        raise ProducerAdmissionAuthorityError("TRUSTED_REPLAY_WORKER_HASH_INVALID")
    if any(ch not in "0123456789abcdef" for ch in worker_hash.lower()):
        raise ProducerAdmissionAuthorityError("TRUSTED_REPLAY_WORKER_HASH_INVALID")
    return {
        "replay_version": REPLAY_VERSION,
        "source_policy_version": SOURCE_POLICY_VERSION,
        "process_isolation_enforced": True,
        "worker_module_sha256": worker_hash.lower(),
        "wall_timeout_seconds": float(MAX_REPLAY_WALL_SECONDS),
        **exact_limits,
    }


def _verify_source_bundle_security_contract(candidate: Dict[str, Any]) -> Dict[str, Any]:
    source_bundle = candidate.get("source_bundle")
    if not isinstance(source_bundle, dict):
        raise ProducerAdmissionAuthorityError("SOURCE_BUNDLE_SECURITY_CONTRACT_MISSING")
    if source_bundle.get("bundle_version") != BUNDLE_VERSION:
        raise ProducerAdmissionAuthorityError("SOURCE_BUNDLE_SECURITY_VERSION_MISMATCH")
    required_true = (
        "static_dependency_closure_recomputed",
        "dynamic_import_policy_recomputed",
        "prohibited_source_paths_blocked",
        "owned_output_replacement_only",
    )
    for key in required_true:
        if source_bundle.get(key) is not True:
            raise ProducerAdmissionAuthorityError("SOURCE_BUNDLE_REQUIRED_GUARD_MISSING:" + key)
    marker_hash = source_bundle.get("ownership_marker_sha256")
    if not isinstance(marker_hash, str) or len(marker_hash) != 64:
        raise ProducerAdmissionAuthorityError("SOURCE_BUNDLE_OWNERSHIP_MARKER_HASH_INVALID")
    try:
        int(marker_hash, 16)
    except ValueError as exc:
        raise ProducerAdmissionAuthorityError("SOURCE_BUNDLE_OWNERSHIP_MARKER_HASH_INVALID") from exc
    return {
        "bundle_version": BUNDLE_VERSION,
        "static_dependency_closure_recomputed": True,
        "dynamic_import_policy_recomputed": True,
        "prohibited_source_paths_blocked": True,
        "owned_output_replacement_only": True,
        "ownership_marker_sha256": marker_hash.lower(),
    }


def _verify_reference_source_contract(reference: Dict[str, Any]) -> Dict[str, Any]:
    if reference.get("source_bundle_version") != BUNDLE_VERSION:
        raise ProducerAdmissionAuthorityError("REFERENCE_SOURCE_BUNDLE_VERSION_MISMATCH")
    required_true = (
        "source_bundle_static_closure_recomputed",
        "source_bundle_dynamic_import_policy_recomputed",
        "source_bundle_prohibited_paths_blocked",
        "reference_generated_by_exact_canonical_source_executor",
        "causal_fixture_only",
    )
    for key in required_true:
        if reference.get(key) is not True:
            raise ProducerAdmissionAuthorityError("REFERENCE_SOURCE_REQUIRED_GUARD_MISSING:" + key)
    required_false = (
        "future_rows_available",
        "outcome_columns_available",
        "final_holdout_accessed",
        "strategy_retuned",
    )
    for key in required_false:
        if reference.get(key) is not False:
            raise ProducerAdmissionAuthorityError("REFERENCE_SOURCE_FORBIDDEN_GUARD_ENABLED:" + key)
    return {
        "source_bundle_version": BUNDLE_VERSION,
        "source_bundle_static_closure_recomputed": True,
        "source_bundle_dynamic_import_policy_recomputed": True,
        "source_bundle_prohibited_paths_blocked": True,
        "reference_generated_by_exact_canonical_source_executor": True,
    }


def verify_producer_admission(
    root: Path,
    *,
    _reference_executor: Optional[ReferenceExecutor] = None,
) -> Dict[str, Any]:
    """Authoritative producer admission.

    V5 requires independent source, reference and candidate replay boundaries.
    Source Bundle V4 closure/dynamic-import policy is recomputed before the
    reference executor runs and again by candidate admission; the resulting
    proofs are explicitly required here. Production remains fail-closed while
    the exact-source reference executor is unavailable.
    """
    root = Path(root).resolve()
    source_bundle_manifest_path = root / "R7_R1_R6_SOURCE_BUNDLE_MANIFEST.json"
    fixture_path = root / "R7_R1_R6_PARITY_FIXTURES.jsonl"
    reference_stream_path = root / "R7_R1_R6_REFERENCE_STREAM.jsonl"
    reference_attestation_path = root / "R7_R1_R6_REFERENCE_REPLAY.json"

    try:
        reference = verify_reference_replay_evidence(
            root,
            source_bundle_manifest_path,
            fixture_path,
            reference_stream_path,
            reference_attestation_path,
            _executor=_reference_executor,
        )
    except ReferenceReplayError as exc:
        raise ProducerAdmissionAuthorityError("CANONICAL_REFERENCE_REPLAY_FAILED:" + str(exc)) from exc
    reference_source_contract = _verify_reference_source_contract(reference)

    try:
        candidate = verify_v4_candidate_admission(root)
    except Exception as exc:
        raise ProducerAdmissionAuthorityError("V4_CANDIDATE_ADMISSION_FAILED:" + str(exc)) from exc
    if candidate.get("ready") is not True:
        raise ProducerAdmissionAuthorityError("V4_CANDIDATE_ADMISSION_NOT_READY")
    if candidate.get("canonical_parent_zip_sha256") != CANONICAL_R6_ZIP_SHA256:
        raise ProducerAdmissionAuthorityError("V4_CANDIDATE_PARENT_SHA_MISMATCH")
    if candidate.get("final_holdout_accessed") is not False:
        raise ProducerAdmissionAuthorityError("V4_CANDIDATE_HOLDOUT_BOUNDARY_BREACH")
    if candidate.get("strategy_retuned") is not False:
        raise ProducerAdmissionAuthorityError("V4_CANDIDATE_RETUNING_BREACH")

    source_bundle_contract = _verify_source_bundle_security_contract(candidate)
    replay_contract = _verify_trusted_replay_security_contract(candidate)

    parity = candidate.get("parity")
    if not isinstance(parity, dict) or parity.get("parity_pass") is not True:
        raise ProducerAdmissionAuthorityError("V4_CANDIDATE_PARITY_NOT_PASS")
    if parity.get("reference_stream_sha256") != sha256_file(reference_stream_path):
        raise ProducerAdmissionAuthorityError("REFERENCE_STREAM_NOT_BOUND_TO_PARITY")
    if parity.get("fixture_corpus_sha256") != reference.get("fixture_file_sha256"):
        raise ProducerAdmissionAuthorityError("REFERENCE_FIXTURE_NOT_BOUND_TO_PARITY")
    if parity.get("source_bundle_manifest_sha256") != reference.get("source_bundle_manifest_sha256"):
        raise ProducerAdmissionAuthorityError("REFERENCE_SOURCE_BUNDLE_NOT_BOUND_TO_PARITY")

    return {
        **candidate,
        "authority_version": AUTHORITY_VERSION,
        "ready": True,
        "reference_source_security_contract": reference_source_contract,
        "reference_source_security_contract_pass": True,
        "source_bundle_security_contract": source_bundle_contract,
        "source_bundle_security_contract_pass": True,
        "trusted_replay_security_contract": replay_contract,
        "trusted_replay_security_contract_pass": True,
        "canonical_reference_replay": reference,
        "canonical_reference_replay_pass": True,
        "reference_attestation_sha256": sha256_file(reference_attestation_path),
        "final_holdout_accessed": False,
        "strategy_retuned": False,
    }


def producer_admission_status(root: Path) -> Dict[str, Any]:
    try:
        return verify_producer_admission(root)
    except Exception as exc:
        return {
            "authority_version": AUTHORITY_VERSION,
            "ready": False,
            "reason": str(exc),
            "reference_source_security_contract_pass": False,
            "source_bundle_security_contract_pass": False,
            "trusted_replay_security_contract_pass": False,
            "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
            "canonical_reference_replay_pass": False,
            "final_holdout_accessed": False,
            "strategy_retuned": False,
        }
