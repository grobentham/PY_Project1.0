from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from .constants import CANONICAL_R6_ZIP_SHA256
from .r6_integrity import verify_runtime_package_integrity
from .r6_producer_seal import SEAL_VERSION, seal_candidate
from .r6_source_bundle import BUNDLE_VERSION


class FusedReleasePrecheckError(RuntimeError):
    pass


PRECHECK_VERSION = "R7_R1_R6_FUSED_RELEASE_PRECHECK_V4"


def _load_json(path: Path, label: str) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise FusedReleasePrecheckError(label + "_UNREADABLE") from exc
    if not isinstance(data, dict):
        raise FusedReleasePrecheckError(label + "_INVALID")
    return data


def _require_equal(actual: Any, expected: Any, error: str) -> None:
    if actual != expected:
        raise FusedReleasePrecheckError(error)


def _validate_hash(value: Any, error: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise FusedReleasePrecheckError(error)
    try:
        int(value, 16)
    except ValueError as exc:
        raise FusedReleasePrecheckError(error) from exc
    return value.lower()


def _validate_security_contract(seal: Dict[str, Any]) -> Dict[str, Any]:
    _require_equal(
        seal.get("trusted_replay_security_contract_pass"),
        True,
        "SEAL_REPLAY_SECURITY_CONTRACT_NOT_PASS",
    )
    contract = seal.get("trusted_replay_security_contract")
    if not isinstance(contract, dict) or not contract:
        raise FusedReleasePrecheckError("SEAL_REPLAY_SECURITY_CONTRACT_MISSING")
    _require_equal(contract.get("process_isolation_enforced"), True, "SEAL_REPLAY_PROCESS_ISOLATION_NOT_PASS")
    for key in ("replay_version", "source_policy_version"):
        if not isinstance(contract.get(key), str) or not contract.get(key):
            raise FusedReleasePrecheckError("SEAL_REPLAY_SECURITY_FIELD_INVALID:" + key)
    _validate_hash(contract.get("worker_module_sha256"), "SEAL_REPLAY_WORKER_HASH_INVALID")
    timeout = contract.get("wall_timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or float(timeout) <= 0:
        raise FusedReleasePrecheckError("SEAL_REPLAY_WALL_TIMEOUT_INVALID")
    for key in (
        "max_fixture_count",
        "max_input_depth",
        "max_input_nodes_per_fixture",
        "max_range_items",
        "max_execution_line_events",
    ):
        value = contract.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise FusedReleasePrecheckError("SEAL_REPLAY_RESOURCE_LIMIT_INVALID:" + key)
    return dict(contract)


def _validate_source_contracts(seal: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    _require_equal(
        seal.get("source_bundle_security_contract_pass"),
        True,
        "SEAL_SOURCE_BUNDLE_SECURITY_CONTRACT_NOT_PASS",
    )
    source_contract = seal.get("source_bundle_security_contract")
    if not isinstance(source_contract, dict) or not source_contract:
        raise FusedReleasePrecheckError("SEAL_SOURCE_BUNDLE_SECURITY_CONTRACT_MISSING")
    _require_equal(source_contract.get("bundle_version"), BUNDLE_VERSION, "SEAL_SOURCE_BUNDLE_VERSION_MISMATCH")
    for key in (
        "static_dependency_closure_recomputed",
        "dynamic_import_policy_recomputed",
        "prohibited_source_paths_blocked",
        "owned_output_replacement_only",
    ):
        _require_equal(source_contract.get(key), True, "SEAL_SOURCE_BUNDLE_GUARD_NOT_PASS:" + key)
    _validate_hash(source_contract.get("ownership_marker_sha256"), "SEAL_SOURCE_BUNDLE_OWNERSHIP_MARKER_HASH_INVALID")

    _require_equal(
        seal.get("reference_source_security_contract_pass"),
        True,
        "SEAL_REFERENCE_SOURCE_SECURITY_CONTRACT_NOT_PASS",
    )
    reference_contract = seal.get("reference_source_security_contract")
    if not isinstance(reference_contract, dict) or not reference_contract:
        raise FusedReleasePrecheckError("SEAL_REFERENCE_SOURCE_SECURITY_CONTRACT_MISSING")
    _require_equal(
        reference_contract.get("source_bundle_version"),
        BUNDLE_VERSION,
        "SEAL_REFERENCE_SOURCE_BUNDLE_VERSION_MISMATCH",
    )
    for key in (
        "source_bundle_static_closure_recomputed",
        "source_bundle_dynamic_import_policy_recomputed",
        "source_bundle_prohibited_paths_blocked",
        "reference_generated_by_exact_canonical_source_executor",
    ):
        _require_equal(reference_contract.get(key), True, "SEAL_REFERENCE_SOURCE_GUARD_NOT_PASS:" + key)
    return dict(source_contract), dict(reference_contract)


def _validate_supplied_seal(seal: Dict[str, Any]) -> None:
    _require_equal(seal.get("seal_version"), SEAL_VERSION, "SEAL_VERSION_MISMATCH")
    _require_equal(seal.get("canonical_parent_zip_sha256"), CANONICAL_R6_ZIP_SHA256, "SEAL_PARENT_SHA_MISMATCH")
    _require_equal(seal.get("admission_ready"), True, "SEAL_ADMISSION_NOT_READY")
    _validate_source_contracts(seal)
    _validate_security_contract(seal)
    _require_equal(seal.get("canonical_reference_replay_pass"), True, "SEAL_CANONICAL_REFERENCE_REPLAY_NOT_PASS")
    _require_equal(seal.get("trusted_producer_replay_pass"), True, "SEAL_TRUSTED_REPLAY_NOT_PASS")
    _require_equal(seal.get("producer_source_policy_pass"), True, "SEAL_SOURCE_POLICY_NOT_PASS")
    _require_equal(seal.get("baseline_mutated"), False, "SEAL_BASELINE_MUTATION_CLAIM")
    _require_equal(seal.get("execution_unlocked"), False, "SEAL_EXECUTION_UNLOCK_CLAIM")
    _require_equal(seal.get("final_holdout_accessed"), False, "SEAL_HOLDOUT_BOUNDARY_BREACH")
    _require_equal(seal.get("strategy_retuned"), False, "SEAL_RETUNING_BREACH")
    authority_version = seal.get("authority_version")
    if not isinstance(authority_version, str) or not authority_version:
        raise FusedReleasePrecheckError("SEAL_AUTHORITY_VERSION_MISSING")
    hashes = seal.get("candidate_files_sha256")
    if not isinstance(hashes, dict) or not hashes:
        raise FusedReleasePrecheckError("SEAL_CANDIDATE_HASHES_MISSING")
    for relative, digest in hashes.items():
        if not isinstance(relative, str) or not relative:
            raise FusedReleasePrecheckError("SEAL_CANDIDATE_PATH_INVALID")
        _validate_hash(digest, "SEAL_CANDIDATE_HASH_INVALID:" + str(relative))
    for key in (
        "producer_module_sha256",
        "fixture_corpus_sha256",
        "producer_replay_attestation_sha256",
        "reference_stream_sha256",
        "reference_replay_attestation_sha256",
        "producer_stream_sha256",
    ):
        _validate_hash(seal.get(key), "SEAL_HASH_INVALID:" + key)


def verify_fused_release_precheck(
    runtime_root: Path,
    candidate_root: Path,
    supplied_seal_path: Path,
) -> Dict[str, Any]:
    """Prove a V4-sealed producer candidate is eligible for a future fused build.

    This function is deliberately non-promoting. It never writes into the
    baseline runtime, never changes CAUSAL_R6_PRODUCER_READY and never creates
    an execution-enabled package. It verifies the locked baseline package,
    freshly re-runs current V5 source/reference/replay authority, and requires
    every source-provenance and replay-security contract in the supplied V4
    seal to match the freshly generated seal.
    """
    runtime_root = Path(runtime_root).resolve()
    candidate_root = Path(candidate_root).resolve()
    supplied_seal_path = Path(supplied_seal_path).resolve()

    try:
        baseline_integrity = verify_runtime_package_integrity(runtime_root)
    except Exception as exc:
        raise FusedReleasePrecheckError("BASELINE_PACKAGE_INTEGRITY_FAILED:" + str(exc)) from exc
    if baseline_integrity.get("causal_r6_producer_ready") is not False:
        raise FusedReleasePrecheckError("BASELINE_PRODUCER_LOCK_NOT_FALSE")
    if baseline_integrity.get("execution_runtime_hard_locked") is not True:
        raise FusedReleasePrecheckError("BASELINE_EXECUTION_NOT_HARD_LOCKED")

    supplied = _load_json(supplied_seal_path, "SUPPLIED_SEAL")
    _validate_supplied_seal(supplied)

    try:
        fresh = seal_candidate(runtime_root, candidate_root)
    except Exception as exc:
        raise FusedReleasePrecheckError("FRESH_CANDIDATE_SEAL_FAILED:" + str(exc)) from exc
    _validate_supplied_seal(fresh)

    authority_fields = (
        "seal_version",
        "canonical_parent_zip_sha256",
        "candidate_files_sha256",
        "producer_module",
        "producer_module_sha256",
        "fixture_corpus_sha256",
        "producer_replay_attestation_sha256",
        "reference_stream_sha256",
        "reference_replay_attestation_sha256",
        "producer_stream_sha256",
        "admission_version",
        "authority_version",
        "admission_ready",
        "reference_source_security_contract_pass",
        "reference_source_security_contract",
        "source_bundle_security_contract_pass",
        "source_bundle_security_contract",
        "trusted_replay_security_contract_pass",
        "trusted_replay_security_contract",
        "canonical_reference_replay_pass",
        "trusted_producer_replay_pass",
        "producer_source_policy_pass",
        "baseline_mutated",
        "execution_unlocked",
        "final_holdout_accessed",
        "strategy_retuned",
    )
    mismatches = [field for field in authority_fields if supplied.get(field) != fresh.get(field)]
    if mismatches:
        raise FusedReleasePrecheckError("STALE_OR_MISMATCHED_SEAL:" + ",".join(mismatches))

    return {
        "precheck_version": PRECHECK_VERSION,
        "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
        "baseline_package_integrity": "PASS",
        "baseline_causal_r6_producer_ready": False,
        "baseline_execution_hard_locked": True,
        "fresh_seal_matches_supplied_seal": True,
        "producer_module": fresh["producer_module"],
        "producer_module_sha256": fresh["producer_module_sha256"],
        "fixture_corpus_sha256": fresh["fixture_corpus_sha256"],
        "producer_replay_attestation_sha256": fresh["producer_replay_attestation_sha256"],
        "reference_stream_sha256": fresh["reference_stream_sha256"],
        "reference_replay_attestation_sha256": fresh["reference_replay_attestation_sha256"],
        "producer_stream_sha256": fresh["producer_stream_sha256"],
        "candidate_files_sha256": fresh["candidate_files_sha256"],
        "admission_version": fresh["admission_version"],
        "authority_version": fresh["authority_version"],
        "candidate_admission_ready": True,
        "reference_source_security_contract_pass": True,
        "reference_source_security_contract": fresh["reference_source_security_contract"],
        "source_bundle_security_contract_pass": True,
        "source_bundle_security_contract": fresh["source_bundle_security_contract"],
        "trusted_replay_security_contract_pass": True,
        "trusted_replay_security_contract": fresh["trusted_replay_security_contract"],
        "canonical_reference_replay_pass": True,
        "trusted_producer_replay_pass": True,
        "producer_source_policy_pass": True,
        "eligible_for_future_fused_build": True,
        "fused_package_created": False,
        "readiness_switch_changed": False,
        "execution_unlocked": False,
        "final_holdout_accessed": False,
        "strategy_retuned": False,
        "successor_release_required": True,
        "note": "PASS means the V4-sealed candidate matched a fresh V5 admission including pre-reference source provenance, canonical-reference replay and isolated replay-security authority. This precheck does not integrate code, alter readiness, or enable trading.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Precheck a V4-sealed R6 producer candidate for a future fused release")
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--seal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify_fused_release_precheck(args.runtime_root, args.candidate_root, args.seal)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
