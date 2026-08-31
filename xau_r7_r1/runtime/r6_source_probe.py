from __future__ import annotations

import ast
import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .constants import CANONICAL_R6_ZIP_SHA256


class R6SourceProbeError(RuntimeError):
    pass


PROBE_VERSION = "R7_R1_R6_SOURCE_PROBE_V1"

_REQUIRED_SOURCE_FILES = (
    "v16r6/engine.py",
    "v16r5/engine.py",
    "V16_R5_MAIN.py",
)

_REQUIRED_FUNCTIONS = {
    "v16r6/engine.py": {"build_r6_universe", "build_r6"},
    "v16r5/engine.py": {"build_r5_universe", "simulate_r5", "summary", "component_audit"},
}


@dataclass(frozen=True)
class FunctionSignature:
    name: str
    positional: List[str]
    keyword_only: List[str]
    vararg: Optional[str]
    kwarg: Optional[str]
    positional_defaults: int
    keyword_defaults: int


@dataclass(frozen=True)
class SourceFileProbe:
    relative_path: str
    sha256: str
    size_bytes: int
    imports: List[str]
    functions: List[FunctionSignature]
    classes: List[str]
    assigned_names: List[str]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize_module(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Import):
        return None
    if isinstance(node, ast.ImportFrom):
        prefix = "." * int(node.level or 0)
        return prefix + str(node.module or "")
    return None


def _function_signature(node: ast.AST) -> FunctionSignature:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise TypeError("function node required")
    args = node.args
    positional_nodes = list(args.posonlyargs) + list(args.args)
    keyword_only = [a.arg for a in args.kwonlyargs]
    return FunctionSignature(
        name=node.name,
        positional=[a.arg for a in positional_nodes],
        keyword_only=keyword_only,
        vararg=None if args.vararg is None else args.vararg.arg,
        kwarg=None if args.kwarg is None else args.kwarg.arg,
        positional_defaults=len(args.defaults),
        keyword_defaults=sum(1 for d in args.kw_defaults if d is not None),
    )


def _assigned_names(tree: ast.Module) -> List[str]:
    names = set()
    for node in tree.body:
        targets: Iterable[ast.AST]
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return sorted(names)


def _imports(tree: ast.Module) -> List[str]:
    out = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = _normalize_module(node)
            imported = ",".join(sorted(alias.name for alias in node.names))
            out.add(f"{module}:{imported}")
    return sorted(out)


def _probe_file(path: Path, relative_path: str) -> SourceFileProbe:
    try:
        raw = path.read_bytes()
    except Exception as exc:
        raise R6SourceProbeError(f"R6_SOURCE_READ_FAILED:{relative_path}:{exc}") from exc
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise R6SourceProbeError(f"R6_SOURCE_NOT_UTF8:{relative_path}") from exc
    try:
        tree = ast.parse(text, filename=relative_path)
    except SyntaxError as exc:
        raise R6SourceProbeError(f"R6_SOURCE_AST_PARSE_FAILED:{relative_path}:{exc}") from exc

    functions = [
        _function_signature(node)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    classes = sorted(node.name for node in tree.body if isinstance(node, ast.ClassDef))
    return SourceFileProbe(
        relative_path=relative_path,
        sha256=_sha256_bytes(raw),
        size_bytes=len(raw),
        imports=_imports(tree),
        functions=functions,
        classes=classes,
        assigned_names=_assigned_names(tree),
    )


def _resolve_exact(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise R6SourceProbeError(f"R6_SOURCE_PATH_ESCAPE:{relative}") from exc
    if not path.is_file():
        raise R6SourceProbeError(f"R6_SOURCE_FILE_MISSING:{relative}")
    return path


def probe_frozen_r6_source(root: Path) -> Dict:
    """AST-map the protected frozen R5/R6 source without importing or executing it.

    This deliberately reads source code only. It does not read trade outcomes,
    validation ledgers, Final Holdout data, or market data.
    """
    root = Path(root).resolve()
    files: Dict[str, SourceFileProbe] = {}
    for relative in _REQUIRED_SOURCE_FILES:
        files[relative] = _probe_file(_resolve_exact(root, relative), relative)

    missing_functions: Dict[str, List[str]] = {}
    for relative, required in _REQUIRED_FUNCTIONS.items():
        actual = {f.name for f in files[relative].functions}
        missing = sorted(required - actual)
        if missing:
            missing_functions[relative] = missing
    if missing_functions:
        detail = ";".join(f"{path}:{','.join(names)}" for path, names in sorted(missing_functions.items()))
        raise R6SourceProbeError("R6_REQUIRED_ENGINE_FUNCTIONS_MISSING:" + detail)

    r6_assigned = set(files["v16r6/engine.py"].assigned_names)
    if "RETIRED_SOURCE" not in r6_assigned:
        raise R6SourceProbeError("R6_RETIRED_SOURCE_ASSIGNMENT_MISSING")

    return {
        "probe_version": PROBE_VERSION,
        "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
        "source_only_probe": True,
        "final_holdout_accessed": False,
        "strategy_executed": False,
        "strategy_retuned": False,
        "producer_admitted": False,
        "required_engine_contract_present": True,
        "files": {
            relative: {
                **{k: v for k, v in asdict(probe).items() if k != "functions"},
                "functions": [asdict(f) for f in probe.functions],
            }
            for relative, probe in files.items()
        },
    }
