from __future__ import annotations

import argparse
import ast
import builtins
import copy
import hashlib
import inspect
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .r6_integrity import sha256_file


class ProducerReplayError(RuntimeError):
    pass


REPLAY_VERSION = "R7_R1_R6_PRODUCER_REPLAY_V2"
SOURCE_POLICY_VERSION = "R7_R1_R6_PRODUCER_SOURCE_POLICY_V2"
FIXTURE_SCHEMA = "V16_R6_CAUSAL_PRODUCER_FIXTURE_V1"
PRODUCER_ENTRYPOINT = "produce"
MAX_FIXTURE_FILE_BYTES = 64 * 1024 * 1024

# The candidate is deliberately import-free. Exact frozen behavior must be
# expressed as a pure transformation of the supplied causal input. This keeps
# replay verification independent of filesystem, network, environment, clock,
# broker, model-file and dynamically imported state.
_SAFE_BUILTIN_NAMES = frozenset({
    "abs", "all", "any", "bool", "dict", "enumerate", "float", "int",
    "len", "list", "max", "min", "pow", "range", "reversed", "round",
    "set", "sorted", "str", "sum", "tuple", "zip",
    "ArithmeticError", "Exception", "KeyError", "TypeError", "ValueError",
})
_FORBIDDEN_CALL_NAMES = frozenset({
    "__import__", "breakpoint", "compile", "delattr", "dir", "eval", "exec",
    "getattr", "globals", "help", "input", "locals", "open", "setattr",
    "vars", "memoryview",
})
_FORBIDDEN_STRING_TOKENS = (
    "final_holdout",
    "research_consumed_validation",
    "protected_validation",
    "retrospective_research",
    "validation_result",
)
_PROHIBITED_INPUT_KEY_TOKENS = (
    "future",
    "holdout",
    "label",
    "outcome",
    "realized_pnl",
    "trade_result",
    "validation_result",
)
_REQUIRED_FIXTURE_FIELDS = frozenset({"schema", "fixture_id", "available_through_ms", "producer_input"})


def _literal_only(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_literal_only(x) for x in node.elts)
    if isinstance(node, ast.Dict):
        return all((k is None or _literal_only(k)) and _literal_only(v) for k, v in zip(node.keys, node.values))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _literal_only(node.operand)
    return False


def verify_producer_source_policy(path: Path) -> Dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise ProducerReplayError("PRODUCER_SOURCE_MISSING")
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except Exception as exc:
        raise ProducerReplayError("PRODUCER_SOURCE_PARSE_FAILED") from exc

    produce_defs = 0
    helper_functions: List[str] = []
    for top in tree.body:
        if isinstance(top, (ast.Import, ast.ImportFrom)):
            raise ProducerReplayError("PRODUCER_IMPORT_FORBIDDEN")
        if isinstance(top, ast.FunctionDef):
            helper_functions.append(top.name)
            if top.name == PRODUCER_ENTRYPOINT:
                produce_defs += 1
        elif isinstance(top, ast.Assign):
            if not _literal_only(top.value):
                raise ProducerReplayError("PRODUCER_TOP_LEVEL_NONLITERAL_ASSIGNMENT")
        elif isinstance(top, ast.AnnAssign):
            if top.value is not None and not _literal_only(top.value):
                raise ProducerReplayError("PRODUCER_TOP_LEVEL_NONLITERAL_ASSIGNMENT")
        elif isinstance(top, ast.Expr) and isinstance(top.value, ast.Constant) and isinstance(top.value.value, str):
            pass
        else:
            raise ProducerReplayError("PRODUCER_TOP_LEVEL_EXECUTION_FORBIDDEN:" + top.__class__.__name__)

    if produce_defs != 1:
        raise ProducerReplayError(f"PRODUCER_ENTRYPOINT_COUNT_INVALID:{produce_defs}")

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ProducerReplayError("PRODUCER_IMPORT_FORBIDDEN")
        if isinstance(node, (ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.YieldFrom)):
            raise ProducerReplayError("PRODUCER_ASYNC_OR_GENERATOR_FORBIDDEN")
        if isinstance(node, (ast.ClassDef, ast.Global, ast.Nonlocal)):
            raise ProducerReplayError("PRODUCER_STATEFUL_CONSTRUCT_FORBIDDEN:" + node.__class__.__name__)
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                raise ProducerReplayError("PRODUCER_DUNDER_ATTRIBUTE_FORBIDDEN:" + node.attr)
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ProducerReplayError("PRODUCER_DUNDER_NAME_FORBIDDEN:" + node.id)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_CALL_NAMES:
                raise ProducerReplayError("PRODUCER_CALL_FORBIDDEN:" + node.func.id)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.lower()
            if any(token in lowered for token in _FORBIDDEN_STRING_TOKENS):
                raise ProducerReplayError("PRODUCER_PROHIBITED_DATA_REFERENCE")

    return {
        "source_policy_version": SOURCE_POLICY_VERSION,
        "producer_module_sha256": sha256_file(path),
        "entrypoint": PRODUCER_ENTRYPOINT,
        "helper_functions": sorted(set(helper_functions) - {PRODUCER_ENTRYPOINT}),
        "imports_allowed": False,
        "classes_allowed": False,
        "dunder_access_allowed": False,
        "filesystem_api_allowed": False,
        "network_api_allowed": False,
        "dynamic_import_allowed": False,
        "prohibited_data_reference_allowed": False,
        "source_policy_pass": True,
    }


def _walk_input(value: Any, *, cutoff: int, path: str = "input") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProducerReplayError("FIXTURE_NONFINITE_NUMBER:" + path)
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            _walk_input(item, cutoff=cutoff, path=f"{path}[{i}]")
        return
    if not isinstance(value, dict):
        raise ProducerReplayError("FIXTURE_NON_JSON_INPUT:" + path)
    for raw_key, child in value.items():
        if not isinstance(raw_key, str) or not raw_key:
            raise ProducerReplayError("FIXTURE_INPUT_KEY_INVALID:" + path)
        key = raw_key.lower()
        if any(token in key for token in _PROHIBITED_INPUT_KEY_TOKENS):
            raise ProducerReplayError("FIXTURE_PROHIBITED_INPUT_KEY:" + raw_key)
        if isinstance(child, int) and not isinstance(child, bool):
            is_time = key.endswith("_ms") and any(token in key for token in ("time", "timestamp", "bar", "emitted", "signal"))
            if is_time and child > cutoff:
                raise ProducerReplayError("FIXTURE_TIMESTAMP_AFTER_PREFIX:" + raw_key)
        _walk_input(child, cutoff=cutoff, path=path + "." + raw_key)


def load_fixtures(path: Path) -> List[Dict[str, Any]]:
    path = Path(path).resolve()
    if not path.is_file():
        raise ProducerReplayError("FIXTURE_FILE_MISSING")
    if path.stat().st_size <= 0 or path.stat().st_size > MAX_FIXTURE_FILE_BYTES:
        raise ProducerReplayError("FIXTURE_FILE_SIZE_INVALID")
    rows: List[Dict[str, Any]] = []
    seen = set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise ProducerReplayError(f"FIXTURE_BLANK_LINE:{line_no}")
        try:
            row = json.loads(line)
        except Exception as exc:
            raise ProducerReplayError(f"FIXTURE_BAD_JSON:{line_no}") from exc
        if not isinstance(row, dict) or set(row) != _REQUIRED_FIXTURE_FIELDS:
            raise ProducerReplayError(f"FIXTURE_SCHEMA_FIELDS_INVALID:{line_no}")
        if row.get("schema") != FIXTURE_SCHEMA:
            raise ProducerReplayError(f"FIXTURE_SCHEMA_MISMATCH:{line_no}")
        fixture_id = row.get("fixture_id")
        if not isinstance(fixture_id, str) or not fixture_id or fixture_id in seen:
            raise ProducerReplayError(f"FIXTURE_ID_INVALID:{line_no}")
        cutoff = row.get("available_through_ms")
        if isinstance(cutoff, bool) or not isinstance(cutoff, int) or cutoff <= 0:
            raise ProducerReplayError(f"FIXTURE_CUTOFF_INVALID:{line_no}")
        producer_input = row.get("producer_input")
        if not isinstance(producer_input, dict):
            raise ProducerReplayError(f"FIXTURE_INPUT_MUST_BE_OBJECT:{line_no}")
        _walk_input(producer_input, cutoff=cutoff)
        seen.add(fixture_id)
        rows.append(row)
    if not rows:
        raise ProducerReplayError("FIXTURE_FILE_EMPTY")
    return rows


def _load_producer(path: Path):
    source_policy = verify_producer_source_policy(path)
    source = Path(path).read_text(encoding="utf-8")
    safe_builtins = {name: getattr(builtins, name) for name in _SAFE_BUILTIN_NAMES}
    namespace: Dict[str, Any] = {
        "__name__": "r7_causal_producer_candidate",
        "__builtins__": safe_builtins,
        "math": math,
    }
    try:
        code = compile(source, str(path), "exec")
        exec(code, namespace, namespace)
    except Exception as exc:
        raise ProducerReplayError("PRODUCER_IMPORT_EXECUTION_FAILED:" + exc.__class__.__name__) from exc
    fn = namespace.get(PRODUCER_ENTRYPOINT)
    if not callable(fn):
        raise ProducerReplayError("PRODUCER_ENTRYPOINT_NOT_CALLABLE")
    try:
        params = list(inspect.signature(fn).parameters.values())
    except Exception as exc:
        raise ProducerReplayError("PRODUCER_ENTRYPOINT_SIGNATURE_UNREADABLE") from exc
    if len(params) != 1 or params[0].kind not in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
        raise ProducerReplayError("PRODUCER_ENTRYPOINT_SIGNATURE_INVALID")
    return fn, source_policy


def _canonical_stream_bytes(rows: List[Dict[str, Any]]) -> bytes:
    text = "\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows) + "\n"
    return text.encode("utf-8")


def replay_producer(fixture_path: Path, producer_module_path: Path) -> Tuple[bytes, Dict[str, Any]]:
    fixture_path = Path(fixture_path).resolve()
    producer_module_path = Path(producer_module_path).resolve()
    fixtures = load_fixtures(fixture_path)
    fn, source_policy = _load_producer(producer_module_path)
    output_rows: List[Dict[str, Any]] = []
    for row in fixtures:
        original = copy.deepcopy(row["producer_input"])
        before = json.dumps(original, sort_keys=True, separators=(",", ":"), allow_nan=False)
        results = []
        for _ in range(2):
            candidate_input = copy.deepcopy(original)
            try:
                result = fn(candidate_input)
            except Exception as exc:
                raise ProducerReplayError("PRODUCER_EXECUTION_FAILED:" + row["fixture_id"] + ":" + exc.__class__.__name__) from exc
            after = json.dumps(candidate_input, sort_keys=True, separators=(",", ":"), allow_nan=False)
            if after != before:
                raise ProducerReplayError("PRODUCER_MUTATED_INPUT:" + row["fixture_id"])
            if result is not None and not isinstance(result, dict):
                raise ProducerReplayError("PRODUCER_RESULT_MUST_BE_OBJECT_OR_NULL:" + row["fixture_id"])
            try:
                canonical_result = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
            except Exception as exc:
                raise ProducerReplayError("PRODUCER_RESULT_NOT_CANONICAL_JSON:" + row["fixture_id"]) from exc
            results.append(canonical_result)
        if results[0] != results[1]:
            raise ProducerReplayError("PRODUCER_NONDETERMINISTIC:" + row["fixture_id"])
        decision = json.loads(results[0])
        output_rows.append({
            "fixture_id": row["fixture_id"],
            "available_through_ms": row["available_through_ms"],
            "decision": decision,
        })

    stream_bytes = _canonical_stream_bytes(output_rows)
    stream_hash = hashlib.sha256(stream_bytes).hexdigest()
    report = {
        "replay_version": REPLAY_VERSION,
        "source_policy_version": SOURCE_POLICY_VERSION,
        "fixture_schema": FIXTURE_SCHEMA,
        "fixture_file_sha256": sha256_file(fixture_path),
        "producer_module_sha256": sha256_file(producer_module_path),
        "producer_stream_sha256": stream_hash,
        "fixture_count": len(fixtures),
        "producer_entrypoint": PRODUCER_ENTRYPOINT,
        "deterministic_double_run": True,
        "producer_input_mutation_count": 0,
        "source_policy_pass": source_policy["source_policy_pass"],
        "imports_allowed": False,
        "classes_allowed": False,
        "dunder_access_allowed": False,
        "filesystem_api_allowed": False,
        "network_api_allowed": False,
        "dynamic_import_allowed": False,
        "future_rows_available_to_producer": False,
        "outcome_columns_present": False,
        "final_holdout_accessed": False,
        "strategy_retuned": False,
    }
    return stream_bytes, report


def verify_replay_evidence(
    fixture_path: Path,
    producer_module_path: Path,
    producer_stream_path: Path,
    replay_attestation_path: Path,
) -> Dict[str, Any]:
    stream_bytes, expected = replay_producer(fixture_path, producer_module_path)
    producer_stream_path = Path(producer_stream_path).resolve()
    replay_attestation_path = Path(replay_attestation_path).resolve()
    if not producer_stream_path.is_file():
        raise ProducerReplayError("PRODUCER_STREAM_MISSING")
    if producer_stream_path.read_bytes() != stream_bytes:
        raise ProducerReplayError("PRODUCER_STREAM_NOT_TRUSTED_REPLAY_OUTPUT")
    try:
        actual = json.loads(replay_attestation_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ProducerReplayError("PRODUCER_REPLAY_ATTESTATION_UNREADABLE") from exc
    if not isinstance(actual, dict) or actual != expected:
        raise ProducerReplayError("PRODUCER_REPLAY_ATTESTATION_MISMATCH")
    return expected


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay an import-free pure R6 causal producer against causal fixture inputs")
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--producer-module", type=Path, required=True)
    parser.add_argument("--producer-stream", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    args = parser.parse_args()
    stream_bytes, report = replay_producer(args.fixtures, args.producer_module)
    args.producer_stream.write_bytes(stream_bytes)
    args.attestation.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
