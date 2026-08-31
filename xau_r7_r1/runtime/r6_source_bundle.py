from __future__ import annotations

import argparse
import ast
import hashlib
import json
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Set, Tuple

from .constants import CANONICAL_R6_ZIP_SHA256
from .r6_source_probe import probe_frozen_r6_source


class R6SourceBundleError(RuntimeError):
    pass


BUNDLE_VERSION = "R7_R1_R6_SOURCE_BUNDLE_V3"
REQUIRED_SOURCE_FILES: Tuple[str, ...] = (
    "v16r6/engine.py",
    "v16r5/engine.py",
    "V16_R5_MAIN.py",
)
MAX_SOURCE_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_SOURCE_BYTES = 32 * 1024 * 1024
MAX_DEPENDENCY_FILES = 512
_DYNAMIC_IMPORT_CALLS = {"__import__", "importlib.import_module", "import_module"}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_member(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise R6SourceBundleError("R6_ZIP_MEMBER_NAME_INVALID")
    normalized = name.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if not pure.parts or pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise R6SourceBundleError("R6_ZIP_UNSAFE_MEMBER_PATH:" + name)
    if ":" in pure.parts[0]:
        raise R6SourceBundleError("R6_ZIP_UNSAFE_MEMBER_DRIVE:" + name)
    return pure.as_posix()


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (int(info.external_attr) >> 16) & 0o170000
    return mode == stat.S_IFLNK


def _decode_parse(raw: bytes, relative: str) -> ast.Module:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise R6SourceBundleError("R6_ZIP_SOURCE_NOT_UTF8:" + relative) from exc
    try:
        return ast.parse(text, filename=relative)
    except SyntaxError as exc:
        raise R6SourceBundleError("R6_ZIP_SOURCE_AST_INVALID:" + relative) from exc


def _module_target_candidates(parts: Iterable[str]) -> Set[str]:
    p = [x for x in parts if x]
    if not p:
        return set()
    joined = "/".join(p)
    return {joined + ".py", joined + "/__init__.py"}


def _package_init_candidates(parts: Iterable[str]) -> Set[str]:
    p = [x for x in parts if x]
    return {"/".join(p[:i]) + "/__init__.py" for i in range(1, len(p))}


def _relative_base_module(current_relative: str, node: ast.ImportFrom) -> List[str]:
    current = PurePosixPath(current_relative)
    package = list(current.parent.parts)
    if node.level:
        ascend = int(node.level) - 1
        if ascend > len(package):
            raise R6SourceBundleError("R6_SOURCE_RELATIVE_IMPORT_OUTSIDE_PACKAGE:" + current_relative)
        base = package[: len(package) - ascend] if ascend else package
    else:
        base = []
    if node.module:
        base += str(node.module).split(".")
    return base


def _call_name(call: ast.Call) -> str:
    fn = call.func
    parts: List[str] = []
    while isinstance(fn, ast.Attribute):
        parts.append(fn.attr)
        fn = fn.value
    if isinstance(fn, ast.Name):
        parts.append(fn.id)
        return ".".join(reversed(parts))
    return ""


def _local_roots(available_python: Set[str]) -> Set[str]:
    roots = set()
    for relative in available_python:
        parts = PurePosixPath(relative).parts
        if len(parts) > 1:
            roots.add(parts[0])
    return roots


def _resolve_module(parts: List[str], available: Set[str]) -> Tuple[Set[str], bool]:
    if not parts:
        return set(), False
    target_candidates = _module_target_candidates(parts)
    targets = target_candidates & available
    deps = set(targets)
    deps |= _package_init_candidates(parts) & available
    return deps, bool(targets)


def _import_descriptor(node: ast.AST) -> str:
    if isinstance(node, ast.Import):
        return "import " + ",".join(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        prefix = "." * int(node.level or 0)
        module = prefix + str(node.module or "")
        return "from " + module + " import " + ",".join(alias.name for alias in node.names)
    return ast.dump(node, include_attributes=False)


def _local_import_dependencies(
    relative: str,
    tree: ast.Module,
    available: Set[str],
    local_roots: Set[str],
) -> Tuple[Set[str], Set[str]]:
    """Return archive-local Python deps and unresolved non-archive imports.

    Relative imports and absolute imports rooted in an archive-local package are
    mandatory. If those targets are absent, extraction fails closed. Imports
    with no archive-local package root are recorded as unresolved/non-archive
    (normally stdlib or third-party dependencies) rather than silently erased.
    """
    deps: Set[str] = set()
    unresolved_nonarchive: Set[str] = set()
    dynamic_calls = sorted({_call_name(n) for n in ast.walk(tree) if isinstance(n, ast.Call)} & _DYNAMIC_IMPORT_CALLS)
    if dynamic_calls:
        raise R6SourceBundleError(
            "R6_SOURCE_DYNAMIC_IMPORT_UNRESOLVED:" + relative + ":" + ",".join(dynamic_calls)
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                resolved, target_found = _resolve_module(parts, available)
                if target_found:
                    deps |= resolved
                elif parts[0] in local_roots:
                    raise R6SourceBundleError(
                        "R6_SOURCE_REQUIRED_LOCAL_IMPORT_MISSING:" + relative + ":" + alias.name
                    )
                else:
                    unresolved_nonarchive.add("import " + alias.name)

        elif isinstance(node, ast.ImportFrom):
            base = _relative_base_module(relative, node)
            resolved_base, base_found = _resolve_module(base, available)
            relative_import = int(node.level or 0) > 0
            root_local = bool(base and base[0] in local_roots)

            if base_found:
                deps |= resolved_base
                # Python permits `from package import submodule`; include any
                # archive-local alias module without assuming every imported
                # name is itself a module.
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    alias_resolved, alias_found = _resolve_module(base + alias.name.split("."), available)
                    if alias_found:
                        deps |= alias_resolved
                continue

            if relative_import or root_local:
                raise R6SourceBundleError(
                    "R6_SOURCE_REQUIRED_LOCAL_IMPORT_MISSING:"
                    + relative
                    + ":"
                    + _import_descriptor(node)
                )
            unresolved_nonarchive.add(_import_descriptor(node))

    return deps, unresolved_nonarchive


def _safe_prepare_output(output_root: Path, replace_existing: bool) -> None:
    if output_root.exists():
        if not replace_existing:
            raise R6SourceBundleError("R6_SOURCE_BUNDLE_OUTPUT_EXISTS")
        if output_root.parent == output_root:
            raise R6SourceBundleError("R6_SOURCE_BUNDLE_OUTPUT_ROOT_UNSAFE")
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=False)


def extract_canonical_source_bundle(
    parent_zip: Path,
    output_root: Path,
    *,
    expected_parent_sha256: str = CANONICAL_R6_ZIP_SHA256,
    replace_existing: bool = True,
) -> Dict:
    parent_zip = Path(parent_zip).resolve()
    output_root = Path(output_root).resolve()
    if not parent_zip.is_file():
        raise R6SourceBundleError("CANONICAL_R6_ZIP_MISSING")
    expected = str(expected_parent_sha256).lower()
    if len(expected) != 64:
        raise R6SourceBundleError("EXPECTED_PARENT_SHA256_INVALID")
    actual_parent_sha = _sha256_file(parent_zip)
    if actual_parent_sha != expected:
        raise R6SourceBundleError(
            "CANONICAL_R6_SHA256_MISMATCH:expected=" + expected + ":actual=" + actual_parent_sha
        )

    files: Dict[str, Dict[str, object]] = {}
    dependency_order: List[str] = []
    unresolved_by_file: Dict[str, List[str]] = {}
    try:
        with zipfile.ZipFile(parent_zip, "r") as archive:
            members: Dict[str, zipfile.ZipInfo] = {}
            for info in archive.infolist():
                normalized = _normalize_member(info.filename)
                if info.is_dir():
                    continue
                if normalized in members:
                    raise R6SourceBundleError("R6_ZIP_DUPLICATE_MEMBER:" + normalized)
                members[normalized] = info

            missing = sorted(set(REQUIRED_SOURCE_FILES) - set(members))
            if missing:
                raise R6SourceBundleError("R6_ZIP_REQUIRED_SOURCE_MISSING:" + ",".join(missing))

            available_python = {name for name in members if name.lower().endswith(".py")}
            local_roots = _local_roots(available_python)
            queue: List[str] = list(REQUIRED_SOURCE_FILES)
            queued: Set[str] = set(queue)
            raw_cache: Dict[str, bytes] = {}
            total_bytes = 0

            index = 0
            while index < len(queue):
                relative = queue[index]
                index += 1
                if len(queue) > MAX_DEPENDENCY_FILES:
                    raise R6SourceBundleError("R6_SOURCE_DEPENDENCY_COUNT_LIMIT_EXCEEDED")
                info = members.get(relative)
                if info is None or info.is_dir():
                    raise R6SourceBundleError("R6_SOURCE_DEPENDENCY_MISSING:" + relative)
                if _is_symlink(info):
                    raise R6SourceBundleError("R6_SOURCE_DEPENDENCY_SYMLINK_FORBIDDEN:" + relative)
                if info.file_size < 0 or info.file_size > MAX_SOURCE_FILE_BYTES:
                    raise R6SourceBundleError("R6_ZIP_SOURCE_SIZE_INVALID:" + relative)
                raw = archive.read(info)
                if len(raw) != info.file_size:
                    raise R6SourceBundleError("R6_ZIP_SOURCE_SIZE_MISMATCH:" + relative)
                total_bytes += len(raw)
                if total_bytes > MAX_TOTAL_SOURCE_BYTES:
                    raise R6SourceBundleError("R6_SOURCE_TOTAL_SIZE_LIMIT_EXCEEDED")
                tree = _decode_parse(raw, relative)
                raw_cache[relative] = raw
                dependency_order.append(relative)

                local_deps, unresolved = _local_import_dependencies(
                    relative, tree, available_python, local_roots
                )
                if unresolved:
                    unresolved_by_file[relative] = sorted(unresolved)
                for dep in sorted(local_deps):
                    if dep not in queued:
                        queued.add(dep)
                        queue.append(dep)

            _safe_prepare_output(output_root, replace_existing)
            for relative in dependency_order:
                raw = raw_cache[relative]
                target = (output_root / relative).resolve()
                try:
                    target.relative_to(output_root)
                except ValueError as exc:
                    raise R6SourceBundleError("R6_SOURCE_OUTPUT_PATH_ESCAPE:" + relative) from exc
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                files[relative] = {
                    "sha256": _sha256_bytes(raw),
                    "size_bytes": len(raw),
                    "required_entry_source": relative in REQUIRED_SOURCE_FILES,
                }
    except zipfile.BadZipFile as exc:
        raise R6SourceBundleError("CANONICAL_R6_ZIP_INVALID") from exc

    probe = probe_frozen_r6_source(output_root)
    probe_path = output_root / "R7_R1_R6_SOURCE_PROBE.json"
    probe_path.write_text(json.dumps(probe, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for relative in REQUIRED_SOURCE_FILES:
        probed_hash = str(probe["files"][relative]["sha256"])
        if probed_hash != files[relative]["sha256"]:
            raise R6SourceBundleError("R6_SOURCE_PROBE_HASH_DISAGREEMENT:" + relative)

    manifest = {
        "bundle_version": BUNDLE_VERSION,
        "canonical_parent_zip_sha256": actual_parent_sha,
        "source_only_bundle": True,
        "static_local_python_dependency_closure_extracted": True,
        "required_local_imports_resolved": True,
        "dynamic_imports_allowed": False,
        "dependency_count": len(dependency_order),
        "required_source_files": list(REQUIRED_SOURCE_FILES),
        "dependency_closure_files": dependency_order,
        "unresolved_nonarchive_imports": unresolved_by_file,
        "strategy_executed": False,
        "strategy_retuned": False,
        "final_holdout_accessed": False,
        "producer_admitted": False,
        "files": files,
        "source_probe_file": probe_path.name,
        "source_probe_sha256": _sha256_file(probe_path),
    }
    manifest_path = output_root / "R7_R1_R6_SOURCE_BUNDLE_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract exact frozen R5/R6 Python source and its archive-local import closure from the canonical R6 ZIP"
    )
    parser.add_argument("--zip", dest="parent_zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = extract_canonical_source_bundle(args.parent_zip, args.output)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
