from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from .constants import CANONICAL_R6_ZIP_SHA256
from .r6_integrity import verify_runtime_package_integrity
from .r6_producer_seal import SEAL_VERSION, seal_candidate


class FusedReleasePrecheckError(RuntimeError):
    pass


PRECHECK_VERSION = "R7_R1_R6_FUSED_RELEASE_PRECHECK_V1"


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


def _validate_supplied_seal(seal: Dict[str, Any]) -> None:
    _require_equal(seal.get("seal_version"), SEAL_VERSION, "SEAL_VERSION_MISMATCH")
    _require_equal(
        seal.get("canonical_parent_zip_sha256"),
        CANONICAL_R6_ZIP_SHA256,
        "SEAL_PARENT_SHA_MISMATCH",
    )
    _require_equal(seal.get("admission_ready"), True, "SEAL_ADMISSION_NOT_READY")
    _require_equal(seal.get("baseline_mutated"), False, "SEAL_BASELINE_MUTATION_CLAIM")
    _require_equal(seal.get("execution_unlocked"), False, "SEAL_EXECUTION_UNLOCK_CLAIM")
    _require_equal(seal.get("final_holdout_accessed"), False, "SEAL_HOLDOUT_BOUNDARY_BREACH")
    _require_equal(seal.get("strategy_retuned"), False, "SEAL_RETUNING_BREACH")
    hashes = seal.get("candidate_files_sha256")
    if not isinstance(hashes, dict) or not hashes:
        raise FusedReleasePrecheckError("SEAL_CANDIDATE_HASHES_MISSING")
    for relative, digest in hashes.items():
        if not isinstance(relative, str) or not relative:
            raise FusedReleasePrecheckError("SEAL_CANDIDATE_PATH_INVALID")
        if not isinstance(digest, str) or len(digest) != 64:
            raise FusedReleasePrecheckError("SEAL_CANDIDATE_HASH_INVALID:" + str(relative))
    producer_hash = seal.get("producer_module_sha256")
    if not isinstance(producer_hash, str) or len(producer_hash) != 64:
        raise FusedReleasePrecheckError("SEAL_PRODUCER_HASH_INVALID")


def verify_fused_release_precheck(
    runtime_root: Path,
    candidate_root: Path,
    supplied_seal_path: Path,
) -> Dict[str, Any]:
    """Prove a sealed producer candidate is eligible for a future fused build.

    This function is deliberately non-promoting. It never writes into the
    baseline runtime, never changes CAUSAL_R6_PRODUCER_READY and never creates
    an execution-enabled package. It verifies the locked baseline package,
    freshly re-runs isolated candidate admission, and requires the supplied
    seal to match that fresh result exactly on all authority-bearing fields.
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
        "admission_version",
        "admission_ready",
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
        "candidate_files_sha256": fresh["candidate_files_sha256"],
        "admission_version": fresh["admission_version"],
        "candidate_admission_ready": True,
        "eligible_for_future_fused_build": True,
        "fused_package_created": False,
        "readiness_switch_changed": False,
        "execution_unlocked": False,
        "final_holdout_accessed": False,
        "strategy_retuned": False,
        "successor_release_required": True,
        "note": "PASS means the sealed candidate is eligible to enter a separate fused-build/certification step. This precheck does not integrate code, alter the readiness constitution, or enable trading.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Precheck a sealed R6 producer candidate for a future fused release")
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
