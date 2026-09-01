from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Tuple

from .constants import CANONICAL_R6_ZIP_SHA256
from .r6_admission_authority import verify_producer_admission
from .r6_integrity import sha256_file
from .r6_source_bundle import BUNDLE_VERSION


class ProducerSealError(RuntimeError):
    pass


SEAL_VERSION = "R7_R1_R6_PRODUCER_CANDIDATE_SEAL_V4"
GENERATED_SEAL_FILENAME = "R7_R1_R6_PRODUCER_CANDIDATE_SEAL.json"
PRODUCER_MODULE_RELATIVE = "r7_runtime/r6_causal_producer.py"
EVIDENCE_FILES: Tuple[str, ...] = (
    "R7_R1_R6_SOURCE_PROBE.json",
    "R7_R1_R6_SOURCE_BUNDLE_MANIFEST.json",
    "R7_R1_R6_PARITY_FIXTURES.jsonl",
    "R7_R1_R6_PRODUCER_REPLAY.json",
    "R7_R1_R6_REFERENCE_STREAM.jsonl",
    "R7_R1_R6_REFERENCE_REPLAY.json",
    "R7_R1_R6_PRODUCER_STREAM.jsonl",
    "R7_R1_R6_PARITY_ISOLATION.json",
    "R7_R1_R6_PRODUCER_PARITY.json",
)
ALLOWED_CANDIDATE_FILES = frozenset((PRODUCER_MODULE_RELATIVE,) + EVIDENCE_FILES)
IGNORED_GENERATED_FILES = frozenset({GENERATED_SEAL_FILENAME})


def _safe_relative(path: Path, root: Path) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ProducerSealError("CANDIDATE_PATH_ESCAPE") from exc
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ProducerSealError("CANDIDATE_PATH_INVALID:" + relative)
    return relative


def _candidate_inventory(candidate_root: Path) -> Dict[str, Path]:
    candidate_root = Path(candidate_root).resolve()
    if not candidate_root.is_dir():
        raise ProducerSealError("CANDIDATE_ROOT_MISSING")
    inventory: Dict[str, Path] = {}
    for path in candidate_root.rglob("*"):
        if path.is_symlink():
            raise ProducerSealError("CANDIDATE_SYMLINK_FORBIDDEN:" + _safe_relative(path, candidate_root))
        if not path.is_file():
            continue
        relative = _safe_relative(path, candidate_root)
        if relative in IGNORED_GENERATED_FILES:
            continue
        if relative in inventory:
            raise ProducerSealError("CANDIDATE_DUPLICATE_PATH:" + relative)
        inventory[relative] = path
    unexpected = sorted(set(inventory) - ALLOWED_CANDIDATE_FILES)
    missing = sorted(ALLOWED_CANDIDATE_FILES - set(inventory))
    if unexpected:
        raise ProducerSealError("CANDIDATE_UNEXPECTED_FILES:" + ",".join(unexpected))
    if missing:
        raise ProducerSealError("CANDIDATE_REQUIRED_FILES_MISSING:" + ",".join(missing))
    return inventory


def _baseline_guard(runtime_root: Path) -> Dict[str, Any]:
    manifest_path = Path(runtime_root) / "R7_R1_PARENT_INTEGRITY.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ProducerSealError("BASELINE_PARENT_MANIFEST_UNREADABLE") from exc
    if not isinstance(manifest, dict):
        raise ProducerSealError("BASELINE_PARENT_MANIFEST_INVALID")
    if manifest.get("canonical_parent_zip_sha256") != CANONICAL_R6_ZIP_SHA256:
        raise ProducerSealError("BASELINE_PARENT_SHA_MISMATCH")
    if manifest.get("build_verified_parent_zip_sha256") != CANONICAL_R6_ZIP_SHA256:
        raise ProducerSealError("BASELINE_BUILD_SHA_MISMATCH")
    if manifest.get("final_holdout_accessed") is not False:
        raise ProducerSealError("BASELINE_HOLDOUT_BOUNDARY_BREACH")
    if manifest.get("strategy_retuned") is not False:
        raise ProducerSealError("BASELINE_RETUNING_BREACH")
    if manifest.get("causal_r6_producer_ready") is not False:
        raise ProducerSealError("BASELINE_MUST_REMAIN_PRODUCER_LOCKED")
    return manifest


def _validate_hash(value: Any, error: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ProducerSealError(error)
    try:
        int(value, 16)
    except ValueError as exc:
        raise ProducerSealError(error) from exc
    return value.lower()


def _require_security_contract(admission: Dict[str, Any]) -> Dict[str, Any]:
    if admission.get("trusted_replay_security_contract_pass") is not True:
        raise ProducerSealError("CANDIDATE_REPLAY_SECURITY_CONTRACT_NOT_PROVEN")
    contract = admission.get("trusted_replay_security_contract")
    if not isinstance(contract, dict) or not contract:
        raise ProducerSealError("CANDIDATE_REPLAY_SECURITY_CONTRACT_MISSING")
    if contract.get("process_isolation_enforced") is not True:
        raise ProducerSealError("CANDIDATE_REPLAY_PROCESS_ISOLATION_NOT_PROVEN")
    _validate_hash(contract.get("worker_module_sha256"), "CANDIDATE_REPLAY_WORKER_HASH_INVALID")
    timeout = contract.get("wall_timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or float(timeout) <= 0:
        raise ProducerSealError("CANDIDATE_REPLAY_WALL_TIMEOUT_INVALID")
    return dict(contract)


def _require_source_security_contracts(admission: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if admission.get("source_bundle_security_contract_pass") is not True:
        raise ProducerSealError("CANDIDATE_SOURCE_BUNDLE_SECURITY_CONTRACT_NOT_PROVEN")
    source_contract = admission.get("source_bundle_security_contract")
    if not isinstance(source_contract, dict) or not source_contract:
        raise ProducerSealError("CANDIDATE_SOURCE_BUNDLE_SECURITY_CONTRACT_MISSING")
    if source_contract.get("bundle_version") != BUNDLE_VERSION:
        raise ProducerSealError("CANDIDATE_SOURCE_BUNDLE_VERSION_MISMATCH")
    for key in (
        "static_dependency_closure_recomputed",
        "dynamic_import_policy_recomputed",
        "prohibited_source_paths_blocked",
        "owned_output_replacement_only",
    ):
        if source_contract.get(key) is not True:
            raise ProducerSealError("CANDIDATE_SOURCE_BUNDLE_GUARD_NOT_PROVEN:" + key)
    _validate_hash(
        source_contract.get("ownership_marker_sha256"),
        "CANDIDATE_SOURCE_BUNDLE_OWNERSHIP_MARKER_HASH_INVALID",
    )

    if admission.get("reference_source_security_contract_pass") is not True:
        raise ProducerSealError("CANDIDATE_REFERENCE_SOURCE_SECURITY_CONTRACT_NOT_PROVEN")
    reference_contract = admission.get("reference_source_security_contract")
    if not isinstance(reference_contract, dict) or not reference_contract:
        raise ProducerSealError("CANDIDATE_REFERENCE_SOURCE_SECURITY_CONTRACT_MISSING")
    if reference_contract.get("source_bundle_version") != BUNDLE_VERSION:
        raise ProducerSealError("CANDIDATE_REFERENCE_SOURCE_BUNDLE_VERSION_MISMATCH")
    for key in (
        "source_bundle_static_closure_recomputed",
        "source_bundle_dynamic_import_policy_recomputed",
        "source_bundle_prohibited_paths_blocked",
        "reference_generated_by_exact_canonical_source_executor",
    ):
        if reference_contract.get(key) is not True:
            raise ProducerSealError("CANDIDATE_REFERENCE_SOURCE_GUARD_NOT_PROVEN:" + key)
    return dict(source_contract), dict(reference_contract)


def seal_candidate(runtime_root: Path, candidate_root: Path) -> Dict[str, Any]:
    runtime_root = Path(runtime_root).resolve()
    candidate_root = Path(candidate_root).resolve()
    if not runtime_root.is_dir():
        raise ProducerSealError("BASELINE_RUNTIME_ROOT_MISSING")
    _baseline_guard(runtime_root)
    inventory = _candidate_inventory(candidate_root)

    before_parent = sha256_file(runtime_root / "R7_R1_PARENT_INTEGRITY.json")
    before_protected: Dict[str, str] = {}
    parent = json.loads((runtime_root / "R7_R1_PARENT_INTEGRITY.json").read_text(encoding="utf-8"))
    protected = parent.get("protected_r6_hashes")
    if not isinstance(protected, dict):
        raise ProducerSealError("BASELINE_PROTECTED_HASHES_MISSING")
    for relative in protected:
        normalized = str(relative).replace("\\", "/")
        path = runtime_root / normalized
        if not path.is_file():
            raise ProducerSealError("BASELINE_PROTECTED_FILE_MISSING:" + normalized)
        before_protected[normalized] = sha256_file(path)

    with tempfile.TemporaryDirectory(prefix="xau_r7_r1_producer_seal_") as td:
        staging = Path(td) / "runtime"
        shutil.copytree(runtime_root, staging, symlinks=False)
        for relative, source in inventory.items():
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

        try:
            admission = verify_producer_admission(staging)
        except Exception as exc:
            raise ProducerSealError("CANDIDATE_ADMISSION_FAILED:" + str(exc)) from exc
        if admission.get("ready") is not True:
            raise ProducerSealError("CANDIDATE_ADMISSION_NOT_READY")
        if admission.get("final_holdout_accessed") is not False:
            raise ProducerSealError("CANDIDATE_HOLDOUT_BOUNDARY_BREACH")
        if admission.get("strategy_retuned") is not False:
            raise ProducerSealError("CANDIDATE_RETUNING_BREACH")
        source_bundle_security_contract, reference_source_security_contract = _require_source_security_contracts(admission)
        replay_security_contract = _require_security_contract(admission)
        if admission.get("canonical_reference_replay_pass") is not True:
            raise ProducerSealError("CANDIDATE_CANONICAL_REFERENCE_REPLAY_NOT_PROVEN")
        canonical_reference = admission.get("canonical_reference_replay")
        if not isinstance(canonical_reference, dict):
            raise ProducerSealError("CANDIDATE_CANONICAL_REFERENCE_EVIDENCE_MISSING")
        for key in (
            "source_bundle_static_closure_recomputed",
            "source_bundle_dynamic_import_policy_recomputed",
            "source_bundle_prohibited_paths_blocked",
            "reference_generated_by_exact_canonical_source_executor",
        ):
            if canonical_reference.get(key) is not True:
                raise ProducerSealError("CANDIDATE_CANONICAL_REFERENCE_SOURCE_GUARD_NOT_PROVEN:" + key)
        if canonical_reference.get("final_holdout_accessed") is not False:
            raise ProducerSealError("CANDIDATE_REFERENCE_HOLDOUT_BOUNDARY_BREACH")
        if canonical_reference.get("strategy_retuned") is not False:
            raise ProducerSealError("CANDIDATE_REFERENCE_RETUNING_BREACH")
        replay = admission.get("trusted_replay")
        if not isinstance(replay, dict) or replay.get("deterministic_double_run") is not True:
            raise ProducerSealError("CANDIDATE_TRUSTED_REPLAY_NOT_PROVEN")
        parity = admission.get("parity")
        if not isinstance(parity, dict) or parity.get("trusted_producer_replay_pass") is not True:
            raise ProducerSealError("CANDIDATE_PARITY_REPLAY_NOT_PROVEN")

    if sha256_file(runtime_root / "R7_R1_PARENT_INTEGRITY.json") != before_parent:
        raise ProducerSealError("BASELINE_PARENT_MANIFEST_MUTATED")
    for relative, digest in before_protected.items():
        if sha256_file(runtime_root / relative) != digest:
            raise ProducerSealError("BASELINE_PROTECTED_FILE_MUTATED:" + relative)

    candidate_hashes = {relative: sha256_file(path) for relative, path in sorted(inventory.items())}
    return {
        "seal_version": SEAL_VERSION,
        "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
        "candidate_files_sha256": candidate_hashes,
        "producer_module": PRODUCER_MODULE_RELATIVE,
        "producer_module_sha256": candidate_hashes[PRODUCER_MODULE_RELATIVE],
        "fixture_corpus_sha256": candidate_hashes["R7_R1_R6_PARITY_FIXTURES.jsonl"],
        "producer_replay_attestation_sha256": candidate_hashes["R7_R1_R6_PRODUCER_REPLAY.json"],
        "reference_stream_sha256": candidate_hashes["R7_R1_R6_REFERENCE_STREAM.jsonl"],
        "reference_replay_attestation_sha256": candidate_hashes["R7_R1_R6_REFERENCE_REPLAY.json"],
        "producer_stream_sha256": candidate_hashes["R7_R1_R6_PRODUCER_STREAM.jsonl"],
        "admission_version": admission.get("admission_version"),
        "authority_version": admission.get("authority_version"),
        "admission_ready": True,
        "reference_source_security_contract_pass": True,
        "reference_source_security_contract": reference_source_security_contract,
        "source_bundle_security_contract_pass": True,
        "source_bundle_security_contract": source_bundle_security_contract,
        "trusted_replay_security_contract_pass": True,
        "trusted_replay_security_contract": replay_security_contract,
        "canonical_reference_replay_pass": True,
        "trusted_producer_replay_pass": True,
        "producer_source_policy_pass": True,
        "baseline_mutated": False,
        "execution_unlocked": False,
        "final_holdout_accessed": False,
        "strategy_retuned": False,
        "note": "V4 candidate seal proves V5 source provenance, pre-reference-execution canonical source authority, exact isolated replay security, trusted producer replay and parity admission in an isolated copy only; it does not change the readiness switch or enable order execution.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seal an R6 causal-producer candidate without mutating the baseline runtime")
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    seal = seal_candidate(args.runtime_root, args.candidate_root)
    args.output.write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(seal, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
