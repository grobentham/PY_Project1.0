from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Tuple

from .constants import CANONICAL_R6_ZIP_SHA256
from .r6_integrity import sha256_file
from .r6_producer_admission import verify_producer_admission


class ProducerSealError(RuntimeError):
    pass


SEAL_VERSION = "R7_R1_R6_PRODUCER_CANDIDATE_SEAL_V1"
GENERATED_SEAL_FILENAME = "R7_R1_R6_PRODUCER_CANDIDATE_SEAL.json"
PRODUCER_MODULE_RELATIVE = "r7_runtime/r6_causal_producer.py"
EVIDENCE_FILES: Tuple[str, ...] = (
    "R7_R1_R6_SOURCE_PROBE.json",
    "R7_R1_R6_SOURCE_BUNDLE_MANIFEST.json",
    "R7_R1_R6_REFERENCE_STREAM.jsonl",
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
        "admission_version": admission.get("admission_version"),
        "admission_ready": True,
        "baseline_mutated": False,
        "execution_unlocked": False,
        "final_holdout_accessed": False,
        "strategy_retuned": False,
        "note": "Candidate seal proves admission in an isolated copy only; it does not change the constitutional readiness switch or enable order execution.",
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
