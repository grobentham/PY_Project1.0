from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict

from .constants import CANONICAL_R6_ZIP_SHA256
from .r6_source_bundle import (
    BUNDLE_VERSION,
    REQUIRED_SOURCE_FILES,
    extract_canonical_source_bundle,
)


class R6BuildSourcePreflightError(RuntimeError):
    pass


PREFLIGHT_VERSION = "R7_R1_CANONICAL_SOURCE_BUILD_PREFLIGHT_V1"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: Path, error: str) -> Dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise R6BuildSourcePreflightError(error) from exc
    if not isinstance(value, dict):
        raise R6BuildSourcePreflightError(error)
    return value


def preflight_canonical_source(
    parent_zip: Path,
    output_root: Path,
    *,
    expected_parent_sha256: str = CANONICAL_R6_ZIP_SHA256,
) -> Dict[str, Any]:
    """Exercise canonical frozen-source extraction without strategy execution.

    This is a release-build gate, not producer admission. It proves that the
    exact parent archive can yield the frozen R5/R6 Python source dependency
    closure and that the source probe recognizes the required engine contract.
    Only a non-sensitive summary is returned; normalized function source stays
    inside the temporary output_root and is removed with the build workspace.
    """
    parent_zip = Path(parent_zip).resolve()
    output_root = Path(output_root).resolve()
    manifest = extract_canonical_source_bundle(
        parent_zip,
        output_root,
        expected_parent_sha256=expected_parent_sha256,
        replace_existing=True,
    )
    probe_path = output_root / "R7_R1_R6_SOURCE_PROBE.json"
    probe = _load_json(probe_path, "CANONICAL_SOURCE_PROBE_UNREADABLE")

    if manifest.get("bundle_version") != BUNDLE_VERSION:
        raise R6BuildSourcePreflightError("CANONICAL_SOURCE_BUNDLE_VERSION_MISMATCH")
    if manifest.get("canonical_parent_zip_sha256") != str(expected_parent_sha256).lower():
        raise R6BuildSourcePreflightError("CANONICAL_SOURCE_PARENT_SHA_MISMATCH")
    if manifest.get("source_only_bundle") is not True:
        raise R6BuildSourcePreflightError("CANONICAL_SOURCE_NOT_SOURCE_ONLY")
    if manifest.get("static_local_python_dependency_closure_extracted") is not True:
        raise R6BuildSourcePreflightError("CANONICAL_SOURCE_CLOSURE_NOT_PROVEN")
    if manifest.get("required_local_imports_resolved") is not True:
        raise R6BuildSourcePreflightError("CANONICAL_SOURCE_LOCAL_IMPORTS_UNRESOLVED")
    if manifest.get("dynamic_imports_allowed") is not False:
        raise R6BuildSourcePreflightError("CANONICAL_SOURCE_DYNAMIC_IMPORTS_ALLOWED")
    if manifest.get("strategy_executed") is not False:
        raise R6BuildSourcePreflightError("CANONICAL_SOURCE_STRATEGY_EXECUTED")
    if manifest.get("strategy_retuned") is not False:
        raise R6BuildSourcePreflightError("CANONICAL_SOURCE_STRATEGY_RETUNED")
    if manifest.get("final_holdout_accessed") is not False:
        raise R6BuildSourcePreflightError("CANONICAL_SOURCE_HOLDOUT_ACCESSED")
    if manifest.get("producer_admitted") is not False:
        raise R6BuildSourcePreflightError("CANONICAL_SOURCE_PRODUCER_ALREADY_ADMITTED")
    if probe.get("required_engine_contract_present") is not True:
        raise R6BuildSourcePreflightError("CANONICAL_SOURCE_ENGINE_CONTRACT_MISSING")
    if probe.get("source_only_probe") is not True:
        raise R6BuildSourcePreflightError("CANONICAL_SOURCE_PROBE_NOT_SOURCE_ONLY")
    if probe.get("strategy_executed") is not False:
        raise R6BuildSourcePreflightError("CANONICAL_SOURCE_PROBE_EXECUTED_STRATEGY")
    if probe.get("strategy_retuned") is not False:
        raise R6BuildSourcePreflightError("CANONICAL_SOURCE_PROBE_RETUNED_STRATEGY")
    if probe.get("final_holdout_accessed") is not False:
        raise R6BuildSourcePreflightError("CANONICAL_SOURCE_PROBE_HOLDOUT_ACCESSED")

    files = manifest.get("files")
    if not isinstance(files, dict):
        raise R6BuildSourcePreflightError("CANONICAL_SOURCE_FILE_MAP_INVALID")
    required_hashes: Dict[str, str] = {}
    for relative in REQUIRED_SOURCE_FILES:
        entry = files.get(relative)
        path = output_root / relative
        if not isinstance(entry, dict) or not path.is_file():
            raise R6BuildSourcePreflightError("CANONICAL_SOURCE_REQUIRED_FILE_MISSING:" + relative)
        expected = str(entry.get("sha256", "")).lower()
        actual = _sha256_file(path)
        if len(expected) != 64 or actual != expected:
            raise R6BuildSourcePreflightError("CANONICAL_SOURCE_REQUIRED_FILE_HASH_MISMATCH:" + relative)
        required_hashes[relative] = actual

    unresolved = manifest.get("unresolved_nonarchive_imports", {})
    if not isinstance(unresolved, dict):
        raise R6BuildSourcePreflightError("CANONICAL_SOURCE_NONARCHIVE_IMPORT_MAP_INVALID")
    unresolved_count = 0
    for values in unresolved.values():
        if not isinstance(values, list):
            raise R6BuildSourcePreflightError("CANONICAL_SOURCE_NONARCHIVE_IMPORT_LIST_INVALID")
        unresolved_count += len(values)

    return {
        "preflight_version": PREFLIGHT_VERSION,
        "canonical_parent_zip_sha256": str(expected_parent_sha256).lower(),
        "bundle_version": BUNDLE_VERSION,
        "source_probe_version": probe.get("probe_version"),
        "source_only_bundle_verified": True,
        "dependency_closure_verified": True,
        "required_engine_contract_verified": True,
        "dependency_count": int(manifest.get("dependency_count", 0)),
        "unresolved_nonarchive_import_count": unresolved_count,
        "required_source_sha256": required_hashes,
        "strategy_executed": False,
        "strategy_retuned": False,
        "final_holdout_accessed": False,
        "producer_admitted": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preflight exact canonical R6 frozen source during release build without executing strategy logic"
    )
    parser.add_argument("--zip", dest="parent_zip", type=Path, required=True)
    parser.add_argument("--output", dest="output_root", type=Path, required=True)
    args = parser.parse_args()
    result = preflight_canonical_source(args.parent_zip, args.output_root)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
