from __future__ import annotations

import argparse
import ast
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .constants import CANONICAL_R6_ZIP_SHA256


class R6SourceProbeError(RuntimeError):
    pass


PROBE_VERSION = "R7_R1_R6_SOURCE_PROBE_V2"

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
class FunctionProbe:
    signature: FunctionSignature
    lineno: int
    end_lineno: int
    ast_sha256: str
    normalized_source: str
    calls: List[str]
    referenced_names: List[str]
    string_literals: List[str]
    numeric_literals: List[float]


@dataclass(frozen=True)
class SourceFileProbe:
    relative_path: str
    sha256: str
    size_bytes: int
    imports: List[str]
    functions: List[FunctionProbe]
    classes: List[str]
    assigned_names: List[str]
    assigned_expressions: Dict[str, str]


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


def _call_name(node: ast.Call) -> Optional[str]:
    fn = node.func
    parts: List[str] = []
    while isinstance(fn, ast.Attribute):
        parts.append(fn.attr)
        fn = fn.value
    if isinstance(fn, ast.Name):
        parts.append(fn.id)
        return ".".join(reversed(parts))
    return None


def _function_probe(node: ast.AST) -> FunctionProbe:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise TypeError("function node required")
    normalized = ast.unparse(node)
    ast_dump = ast.dump(node, annotate_fields=True, include_attributes=False)
    calls = set()
    referenced = set()
    string_literals = set()
    numeric_literals = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = _call_name(child)
            if name:
                calls.add(name)
        elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            referenced.add(child.id)
        elif isinstance(child, ast.Constant):
            value = child.value
            if isinstance(value, str):
                string_literals.add(value)
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                numeric_literals.add(float(value))
    return FunctionProbe(
        signature=_function_signature(node),
        lineno=int(getattr(node, "lineno", 0) or 0),
        end_lineno=int(getattr(node, "end_lineno", 0) or 0),
        ast_sha256=_sha256_bytes(ast_dump.encode("utf-8")),
        normalized_source=normalized,
        calls=sorted(calls),
        referenced_names=sorted(referenced),
        string_literals=sorted(string_literals),
        numeric_literals=sorted(numeric_literals),
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


def _assigned_expressions(tree: ast.Module) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                continue
            out[node.targets[0].id] = ast.unparse(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            out[node.target.id] = ast.unparse(node.value)
    return {key: out[key] for key in sorted(out)}


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
        _function_probe(node)
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
        assigned_expressions=_assigned_expressions(tree),
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
    """AST-map protected frozen R5/R6 source without importing or executing it.

    The report contains semantically normalized function source and dependency
    metadata derived by Python's AST parser. It reads only the three protected
    Python source files and never opens market, outcome, validation, or Holdout
    data.
    """
    root = Path(root).resolve()
    files: Dict[str, SourceFileProbe] = {}
    for relative in _REQUIRED_SOURCE_FILES:
        files[relative] = _probe_file(_resolve_exact(root, relative), relative)

    missing_functions: Dict[str, List[str]] = {}
    for relative, required in _REQUIRED_FUNCTIONS.items():
        actual = {f.signature.name for f in files[relative].functions}
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
        "normalized_ast_source_included": True,
        "final_holdout_accessed": False,
        "strategy_executed": False,
        "strategy_retuned": False,
        "producer_admitted": False,
        "required_engine_contract_present": True,
        "files": {
            relative: {
                **{k: v for k, v in asdict(probe).items() if k != "functions"},
                "functions": [
                    {
                        **{k: v for k, v in asdict(f).items() if k != "signature"},
                        "signature": asdict(f.signature),
                        "name": f.signature.name,
                    }
                    for f in probe.functions
                ],
            }
            for relative, probe in files.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe exact frozen R5/R6 source without executing strategy code")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = probe_frozen_r6_source(args.root)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
