from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from .constants import CANONICAL_R6_ZIP_SHA256, PROTECTED_R6_PATH_SUFFIXES


class IntegrityError(RuntimeError):
    pass


REQUIRED_R7_OPERATOR_FILES = frozenset({
    "PROBE_CANONICAL_R6_SOURCE.ps1",
    "EXTRACT_CANONICAL_R6_PRODUCER_SOURCE.ps1",
    "SEAL_R6_PRODUCER_CANDIDATE.ps1",
    "PRECHECK_R6_FUSED_RELEASE.ps1",
    "R7_R1_PACKAGE_README.md",
    "R7_R1_REPAIR_AUDIT.md",
})


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_manifest(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise IntegrityError("PARENT_INTEGRITY_MANIFEST_MISSING")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise IntegrityError(f"PARENT_INTEGRITY_MANIFEST_UNREADABLE:{exc}") from exc
    if not isinstance(data, dict):
        raise IntegrityError("PARENT_INTEGRITY_MANIFEST_INVALID")
    return data


def _find_suffix(root: Path, suffix: str) -> Path:
    matches = [p for p in root.rglob("*") if p.is_file() and p.as_posix().endswith(suffix)]
    if len(matches) != 1:
        raise IntegrityError(f"PROTECTED_PATH_RESOLUTION_FAILED:{suffix}:matches={len(matches)}")
    return matches[0]


def collect_protected_hashes(root: Path) -> Dict[str, str]:
    root = Path(root).resolve()
    out: Dict[str, str] = {}
    for suffix in PROTECTED_R6_PATH_SUFFIXES:
        p = _find_suffix(root, suffix)
        out[p.relative_to(root).as_posix()] = sha256_file(p)
    return out


def verify_runtime_parent_integrity(root: Path, manifest_path: Optional[Path] = None) -> Dict[str, str]:
    root = Path(root).resolve()
    manifest_path = manifest_path or root / "R7_R1_PARENT_INTEGRITY.json"
    data = _load_manifest(manifest_path)
    expected = data.get("protected_r6_hashes")
    if not isinstance(expected, dict) or not expected:
        raise IntegrityError("PARENT_INTEGRITY_MANIFEST_INVALID")
    actual = collect_protected_hashes(root)
    if set(actual) != set(expected):
        raise IntegrityError("PROTECTED_R6_PATH_SET_CHANGED")
    mismatches = [path for path, digest in expected.items() if actual.get(path) != digest]
    if mismatches:
        raise IntegrityError("PROTECTED_R6_HASH_MISMATCH:" + ",".join(sorted(mismatches)))
    return actual


def verify_parent_tree_unchanged(root: Path, tree_manifest: Path, allowed_changed: Iterable[str] = ("START_XAU.bat",)) -> None:
    root = Path(root).resolve()
    data = _load_manifest(Path(tree_manifest))
    expected = data.get("parent_tree_sha256")
    if not isinstance(expected, dict) or not expected:
        raise IntegrityError("PARENT_TREE_MANIFEST_INVALID")
    allowed = {x.replace("\\", "/") for x in allowed_changed}
    failures = []
    for rel, digest in expected.items():
        rel_norm = str(rel).replace("\\", "/")
        if rel_norm in allowed:
            continue
        p = root / rel_norm
        if not p.is_file() or sha256_file(p) != str(digest):
            failures.append(rel_norm)
    if failures:
        raise IntegrityError("INHERITED_PARENT_FILE_CHANGED:" + ",".join(sorted(failures)))


def _verify_hash_map(root: Path, mapping: Dict[str, str], error_prefix: str) -> None:
    failures = []
    for rel, digest in mapping.items():
        rel_norm = str(rel).replace("\\", "/")
        p = root / rel_norm
        if not p.is_file() or sha256_file(p) != str(digest):
            failures.append(rel_norm)
    if failures:
        raise IntegrityError(error_prefix + ":" + ",".join(sorted(failures)))


def verify_runtime_package_integrity(root: Path, manifest_path: Optional[Path] = None) -> Dict[str, Any]:
    root = Path(root).resolve()
    manifest_path = manifest_path or root / "R7_R1_PARENT_INTEGRITY.json"
    data = _load_manifest(manifest_path)

    if data.get("canonical_parent_zip_sha256") != CANONICAL_R6_ZIP_SHA256:
        raise IntegrityError("MANIFEST_CANONICAL_PARENT_SHA_MISMATCH")
    if data.get("build_verified_parent_zip_sha256") != CANONICAL_R6_ZIP_SHA256:
        raise IntegrityError("BUILD_VERIFIED_PARENT_SHA_MISMATCH")
    if data.get("final_holdout_accessed") is not False:
        raise IntegrityError("FINAL_HOLDOUT_BOUNDARY_NOT_CLEAN")
    if data.get("strategy_retuned") is not False:
        raise IntegrityError("STRATEGY_RETUNING_BOUNDARY_NOT_CLEAN")
    if data.get("demo_only") is not True:
        raise IntegrityError("DEMO_ONLY_MANIFEST_GUARD_MISSING")
    if data.get("execution_enabled_by_default") is not False:
        raise IntegrityError("EXECUTION_DEFAULT_MANIFEST_GUARD_MISSING")
    if data.get("causal_r6_producer_ready") is not False:
        raise IntegrityError("CAUSAL_R6_PRODUCER_LOCK_MANIFEST_GUARD_MISSING")

    verify_parent_tree_unchanged(root, manifest_path)
    protected = verify_runtime_parent_integrity(root, manifest_path)

    original_launcher_hash = data.get("original_start_xau_sha256")
    if not isinstance(original_launcher_hash, str) or len(original_launcher_hash) != 64:
        raise IntegrityError("ORIGINAL_R6_LAUNCHER_HASH_MISSING")
    frozen_launcher = root / "r7_runtime" / "frozen_parent" / "START_XAU_R6_ORIGINAL.bat.txt"
    if not frozen_launcher.is_file() or sha256_file(frozen_launcher) != original_launcher_hash:
        raise IntegrityError("FROZEN_R6_LAUNCHER_HASH_MISMATCH")

    r7_hashes = data.get("r7_runtime_code_sha256")
    if not isinstance(r7_hashes, dict) or not r7_hashes:
        raise IntegrityError("R7_RUNTIME_CODE_HASHES_MISSING")
    _verify_hash_map(root, r7_hashes, "R7_RUNTIME_CODE_HASH_MISMATCH")

    operator_hashes = data.get("r7_operator_tool_sha256")
    if not isinstance(operator_hashes, dict) or not operator_hashes:
        raise IntegrityError("R7_OPERATOR_TOOL_HASHES_MISSING")
    normalized_operator_paths = {str(path).replace("\\", "/") for path in operator_hashes}
    if normalized_operator_paths != REQUIRED_R7_OPERATOR_FILES:
        missing = sorted(REQUIRED_R7_OPERATOR_FILES - normalized_operator_paths)
        extra = sorted(normalized_operator_paths - REQUIRED_R7_OPERATOR_FILES)
        raise IntegrityError(
            "R7_OPERATOR_TOOL_PATH_SET_MISMATCH:missing=" + ",".join(missing) + ";extra=" + ",".join(extra)
        )
    _verify_hash_map(root, operator_hashes, "R7_OPERATOR_TOOL_HASH_MISMATCH")

    return {
        "parent_tree_files": len(data.get("parent_tree_sha256", {})),
        "protected_r6_files": len(protected),
        "r7_runtime_code_files": len(r7_hashes),
        "r7_operator_tool_files": len(operator_hashes),
        "canonical_parent_sha256": CANONICAL_R6_ZIP_SHA256,
        "causal_r6_producer_ready": False,
        "execution_runtime_hard_locked": True,
    }
