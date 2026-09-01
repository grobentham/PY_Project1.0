from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
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

OPERATOR_AUTHORITY_CONTRACT_VERSION = "R7_R1_OPERATOR_AUTHORITY_CONTRACT_V3"
_REQUIRED_EXTRACT_WRAPPER_TOKENS = (
    "R7_R1_R6_SOURCE_BUNDLE_V4",
    "R7_R1_R6_SOURCE_PROBE_V2",
    "prohibited_source_paths_allowed",
    "owned_output_replacement_only",
    "ownership_marker_sha256",
    ".R7_R1_SOURCE_BUNDLE_OWNERSHIP.json",
)
_REQUIRED_SEAL_WRAPPER_TOKENS = (
    "R7_R1_R6_PRODUCER_CANDIDATE_SEAL_V4",
    "R7_R1_R6_SOURCE_BUNDLE_V4",
    "source_bundle_security_contract_pass",
    "reference_source_security_contract_pass",
    "static_dependency_closure_recomputed",
    "source_bundle_static_closure_recomputed",
    "source_bundle_dynamic_import_policy_recomputed",
    "reference_generated_by_exact_canonical_source_executor",
    "R7_R1_R6_PRODUCER_REPLAY_V4",
    "R7_R1_R6_PRODUCER_SOURCE_POLICY_V4",
    "trusted_replay_security_contract_pass",
    "process_isolation_enforced",
    "worker_module_sha256",
    "wall_timeout_seconds",
)
_REQUIRED_PRECHECK_WRAPPER_TOKENS = (
    "R7_R1_R6_FUSED_RELEASE_PRECHECK_V4",
    "R7_R1_R6_SOURCE_BUNDLE_V4",
    "source_bundle_security_contract_pass",
    "reference_source_security_contract_pass",
    "static_dependency_closure_recomputed",
    "source_bundle_static_closure_recomputed",
    "source_bundle_dynamic_import_policy_recomputed",
    "reference_generated_by_exact_canonical_source_executor",
    "R7_R1_R6_PRODUCER_REPLAY_V4",
    "R7_R1_R6_PRODUCER_SOURCE_POLICY_V4",
    "trusted_replay_security_contract_pass",
    "process_isolation_enforced",
    "worker_module_sha256",
    "wall_timeout_seconds",
)
_LEGACY_OPERATOR_TOKENS = (
    "R7_R1_R6_SOURCE_BUNDLE_V3",
    "R7_R1_R6_PRODUCER_CANDIDATE_SEAL_V3",
    "R7_R1_R6_FUSED_RELEASE_PRECHECK_V3",
)


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


def _normalize_relative(value: Any, label: str) -> str:
    relative = str(value).replace("\\", "/")
    pure = PurePosixPath(relative)
    if (
        not relative
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or (pure.parts and ":" in pure.parts[0])
    ):
        raise IntegrityError(label + "_INVALID_PATH:" + relative)
    return pure.as_posix()


def _resolve_manifest_file(root: Path, relative: str, label: str) -> Path:
    root = Path(root).resolve()
    rel = _normalize_relative(relative, label)
    raw = root / rel
    if raw.is_symlink():
        raise IntegrityError(label + "_SYMLINK_FORBIDDEN:" + rel)
    resolved = raw.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise IntegrityError(label + "_PATH_ESCAPE:" + rel) from exc
    return resolved


def _normalize_hash_map(mapping: Any, label: str) -> Dict[str, str]:
    if not isinstance(mapping, dict) or not mapping:
        raise IntegrityError(label + "_MISSING")
    out: Dict[str, str] = {}
    for path, digest in mapping.items():
        relative = _normalize_relative(path, label)
        if relative in out:
            raise IntegrityError(label + "_DUPLICATE_PATH:" + relative)
        digest_text = str(digest).lower()
        if len(digest_text) != 64:
            raise IntegrityError(label + "_INVALID_HASH:" + relative)
        out[relative] = digest_text
    return out


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
    expected = _normalize_hash_map(data.get("protected_r6_hashes"), "PROTECTED_R6_HASHES")
    for suffix in PROTECTED_R6_PATH_SUFFIXES:
        matches = [relative for relative in expected if relative.endswith(suffix)]
        if len(matches) != 1:
            raise IntegrityError(f"PROTECTED_MANIFEST_PATH_RESOLUTION_FAILED:{suffix}:matches={len(matches)}")
    if len(expected) != len(PROTECTED_R6_PATH_SUFFIXES):
        raise IntegrityError("PROTECTED_R6_MANIFEST_PATH_SET_CHANGED")
    actual: Dict[str, str] = {}
    failures = []
    for relative, digest in expected.items():
        path = _resolve_manifest_file(root, relative, "PROTECTED_R6")
        if not path.is_file():
            failures.append(relative)
            continue
        actual_digest = sha256_file(path)
        actual[relative] = actual_digest
        if actual_digest != digest:
            failures.append(relative)
    if failures:
        raise IntegrityError("PROTECTED_R6_HASH_MISMATCH:" + ",".join(sorted(failures)))
    return actual


def verify_parent_tree_unchanged(root: Path, tree_manifest: Path, allowed_changed: Iterable[str] = ("START_XAU.bat",)) -> None:
    root = Path(root).resolve()
    data = _load_manifest(Path(tree_manifest))
    expected = _normalize_hash_map(data.get("parent_tree_sha256"), "PARENT_TREE_HASHES")
    allowed = {_normalize_relative(x, "PARENT_TREE_ALLOWED") for x in allowed_changed}
    failures = []
    for rel, digest in expected.items():
        if rel in allowed:
            continue
        p = _resolve_manifest_file(root, rel, "PARENT_TREE")
        if not p.is_file() or sha256_file(p) != digest:
            failures.append(rel)
    if failures:
        raise IntegrityError("INHERITED_PARENT_FILE_CHANGED:" + ",".join(sorted(failures)))


def _verify_hash_map(root: Path, mapping: Dict[str, str], error_prefix: str) -> None:
    failures = []
    for rel, digest in mapping.items():
        path = _resolve_manifest_file(root, rel, error_prefix)
        if not path.is_file() or sha256_file(path) != str(digest):
            failures.append(rel)
    if failures:
        raise IntegrityError(error_prefix + ":" + ",".join(sorted(failures)))


def _actual_runtime_code_paths(root: Path) -> set[str]:
    root = Path(root).resolve()
    runtime_root = root / "r7_runtime"
    if not runtime_root.is_dir():
        raise IntegrityError("R7_RUNTIME_DIRECTORY_MISSING")
    paths = {
        p.relative_to(root).as_posix()
        for p in runtime_root.rglob("*.py")
        if p.is_file() and not p.is_symlink()
    }
    launcher = root / "START_XAU.bat"
    if not launcher.is_file() or launcher.is_symlink():
        raise IntegrityError("R7_RUNTIME_LAUNCHER_MISSING_OR_SYMLINK")
    paths.add("START_XAU.bat")
    return paths


def _read_operator_text(root: Path, relative: str) -> str:
    path = _resolve_manifest_file(root, relative, "R7_OPERATOR_AUTHORITY")
    if not path.is_file() or path.is_symlink():
        raise IntegrityError("R7_OPERATOR_AUTHORITY_FILE_MISSING:" + relative)
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        raise IntegrityError("R7_OPERATOR_AUTHORITY_FILE_UNREADABLE:" + relative) from exc


def _require_tokens(text: str, tokens: Iterable[str], prefix: str) -> None:
    for token in tokens:
        if token not in text:
            raise IntegrityError(prefix + ":" + token)


def verify_operator_authority_contract(root: Path) -> Dict[str, Any]:
    """Require current certification semantics in addition to matching hashes."""
    root = Path(root).resolve()
    extract_text = _read_operator_text(root, "EXTRACT_CANONICAL_R6_PRODUCER_SOURCE.ps1")
    seal_text = _read_operator_text(root, "SEAL_R6_PRODUCER_CANDIDATE.ps1")
    precheck_text = _read_operator_text(root, "PRECHECK_R6_FUSED_RELEASE.ps1")

    _require_tokens(extract_text, _REQUIRED_EXTRACT_WRAPPER_TOKENS, "R7_OPERATOR_EXTRACT_AUTHORITY_TOKEN_MISSING")
    _require_tokens(seal_text, _REQUIRED_SEAL_WRAPPER_TOKENS, "R7_OPERATOR_SEAL_AUTHORITY_TOKEN_MISSING")
    _require_tokens(precheck_text, _REQUIRED_PRECHECK_WRAPPER_TOKENS, "R7_OPERATOR_PRECHECK_AUTHORITY_TOKEN_MISSING")
    combined = extract_text + "\n" + seal_text + "\n" + precheck_text
    for token in _LEGACY_OPERATOR_TOKENS:
        if token in combined:
            raise IntegrityError("R7_OPERATOR_LEGACY_AUTHORITY_TOKEN_PRESENT:" + token)

    return {
        "operator_authority_contract_version": OPERATOR_AUTHORITY_CONTRACT_VERSION,
        "source_bundle_version": "R7_R1_R6_SOURCE_BUNDLE_V4",
        "source_probe_version": "R7_R1_R6_SOURCE_PROBE_V2",
        "source_owned_output_replacement_required": True,
        "source_prohibited_paths_blocked": True,
        "candidate_seal_version": "R7_R1_R6_PRODUCER_CANDIDATE_SEAL_V4",
        "fused_precheck_version": "R7_R1_R6_FUSED_RELEASE_PRECHECK_V4",
        "source_provenance_contract_required": True,
        "reference_preexecution_source_proof_required": True,
        "producer_replay_version": "R7_R1_R6_PRODUCER_REPLAY_V4",
        "producer_source_policy_version": "R7_R1_R6_PRODUCER_SOURCE_POLICY_V4",
        "replay_security_contract_required": True,
        "process_isolation_required": True,
        "worker_hash_required": True,
        "legacy_v3_rejected": True,
    }


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
    if frozen_launcher.is_symlink() or not frozen_launcher.is_file() or sha256_file(frozen_launcher) != original_launcher_hash:
        raise IntegrityError("FROZEN_R6_LAUNCHER_HASH_MISMATCH")

    r7_hashes = _normalize_hash_map(data.get("r7_runtime_code_sha256"), "R7_RUNTIME_CODE_HASHES")
    actual_runtime_paths = _actual_runtime_code_paths(root)
    if set(r7_hashes) != actual_runtime_paths:
        missing = sorted(actual_runtime_paths - set(r7_hashes))
        extra = sorted(set(r7_hashes) - actual_runtime_paths)
        raise IntegrityError("R7_RUNTIME_CODE_PATH_SET_MISMATCH:untracked=" + ",".join(missing) + ";missing=" + ",".join(extra))
    _verify_hash_map(root, r7_hashes, "R7_RUNTIME_CODE_HASH_MISMATCH")

    operator_hashes = _normalize_hash_map(data.get("r7_operator_tool_sha256"), "R7_OPERATOR_TOOL_HASHES")
    if set(operator_hashes) != REQUIRED_R7_OPERATOR_FILES:
        missing = sorted(REQUIRED_R7_OPERATOR_FILES - set(operator_hashes))
        extra = sorted(set(operator_hashes) - REQUIRED_R7_OPERATOR_FILES)
        raise IntegrityError("R7_OPERATOR_TOOL_PATH_SET_MISMATCH:missing=" + ",".join(missing) + ";extra=" + ",".join(extra))
    _verify_hash_map(root, operator_hashes, "R7_OPERATOR_TOOL_HASH_MISMATCH")
    operator_authority = verify_operator_authority_contract(root)

    return {
        "parent_tree_files": len(data.get("parent_tree_sha256", {})),
        "protected_r6_files": len(protected),
        "r7_runtime_code_files": len(r7_hashes),
        "r7_operator_tool_files": len(operator_hashes),
        "operator_authority_contract": operator_authority,
        "operator_authority_contract_pass": True,
        "canonical_parent_sha256": CANONICAL_R6_ZIP_SHA256,
        "causal_r6_producer_ready": False,
        "execution_runtime_hard_locked": True,
    }