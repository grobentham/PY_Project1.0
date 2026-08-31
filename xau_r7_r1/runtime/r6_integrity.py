from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, Iterable, Optional

from .constants import PROTECTED_R6_PATH_SUFFIXES


class IntegrityError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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
    if not manifest_path.exists():
        raise IntegrityError("PARENT_INTEGRITY_MANIFEST_MISSING")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
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
    data = json.loads(Path(tree_manifest).read_text(encoding="utf-8"))
    expected = data.get("parent_tree_sha256")
    if not isinstance(expected, dict) or not expected:
        raise IntegrityError("PARENT_TREE_MANIFEST_INVALID")
    allowed = {x.replace("\\", "/") for x in allowed_changed}

    failures = []
    for rel, digest in expected.items():
        rel_norm = rel.replace("\\", "/")
        if rel_norm in allowed:
            continue
        p = root / rel
        if not p.is_file() or sha256_file(p) != digest:
            failures.append(rel_norm)
    if failures:
        raise IntegrityError("INHERITED_PARENT_FILE_CHANGED:" + ",".join(sorted(failures)))
