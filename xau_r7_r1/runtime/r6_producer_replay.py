from __future__ import annotations

import argparse
import ast
import builtins
import copy
import hashlib
import inspect
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .r6_integrity import sha256_file


class ProducerReplayError(RuntimeError):
    pass


REPLAY_VERSION = "R7_R1_R6_PRODUCER_REPLAY_V4"
SOURCE_POLICY_VERSION = "R7_R1_R6_PRODUCER_SOURCE_POLICY_V4"
FIXTURE_SCHEMA = "V16_R6_CAUSAL_PRODUCER_FIXTURE_V1"
PRODUCER_ENTRYPOINT = "produce"
MAX_FIXTURE_FILE_BYTES = 64 * 1024 * 1024
MAX_PRODUCER_SOURCE_BYTES = 1024 * 1024
MAX_FIXTURE_COUNT = 4096
MAX_INPUT_DEPTH = 64
MAX_INPUT_NODES_PER_FIXTURE = 100_000
MAX_RANGE_ITEMS = 1_000_000
MAX_EXECUTION_LINE_EVENTS = 1_000_000
MAX_REPLAY_WALL_SECONDS = 60.0
MAX_REPLAY_STREAM_BYTES = 16 * 1024 * 1024
MAX_REPLAY_REPORT_BYTES = 1024 * 1024

# The candidate is deliberately import-free. Exact frozen behavior must be
# expressed as a pure transformation of the supplied causal input. This keeps
# replay verification independent of filesystem, network, environment, clock,
# broker, model-file and dynamically imported state.
_SAFE_BUILTIN_NAMES = frozenset({
    "abs", "all", "any", "bool", "dict", "enumerate", "float", "int",
    "len", "list", "max", "min", "pow", "reversed", "round",
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


def _immutable_literal_only(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Tuple):
        return all(_immutable_literal_only(x) for x in node.elts)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _immutable_literal_only(node.operand)
    return False


def _safe_range(*args):
    try:
        value = range(*args)
    except Exception as exc:
        raise ProducerReplayError("PRODUCER_RANGE_ARGUMENT_INVALID") from exc
    if len(value) > MAX_RANGE_ITEMS:
        raise ProducerReplayError("PRODUCER_RANGE_LIMIT_EXCEEDED")
    return value


def _function_definition_is_pure(node: ast.FunctionDef) -> None:
    if node.decorator_list:
        raise ProducerReplayError("PRODUCER_FUNCTION_DECORATOR_FORBIDDEN:" + node.name)
    annotations = [node.returns]
    annotations.extend(arg.annotation for arg in node.args.posonlyargs)
    annotations.extend(arg.annotation for arg in node.args.args)
    annotations.extend(arg.annotation for arg in node.args.kwonlyargs)
    if node.args.vararg is not None:
        annotations.append(node.args.vararg.annotation)
    if node.args.kwarg is not None:
        annotations.append(node.args.kwarg.annotation)
    if any(annotation is not None for annotation in annotations):
        raise ProducerReplayError("PRODUCER_FUNCTION_ANNOTATION_FORBIDDEN:" + node.name)
    defaults = list(node.args.defaults) + [x for x in node.args.kw_defaults if x is not None]
    if any(not _immutable_literal_only(default) for default in defaults):
        raise ProducerReplayError("PRODUCER_FUNCTION_DEFAULT_NOT_IMMUTABLE_LITERAL:" + node.name)


def verify_producer_source_policy(path: Path) -> Dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise ProducerReplayError("PRODUCER_SOURCE_MISSING")
    if path.stat().st_size <= 0 or path.stat().st_size > MAX_PRODUCER_SOURCE_BYTES:
        raise ProducerReplayError("PRODUCER_SOURCE_SIZE_INVALID")
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
            _function_definition_is_pure(top)
            helper_functions.append(top.name)
            if top.name == PRODUCER_ENTRYPOINT:
                produce_defs += 1
        elif isinstance(top, ast.Assign):
            if not _immutable_literal_only(top.value):
                raise ProducerReplayError("PRODUCER_TOP_LEVEL_MUTABLE_OR_NONLITERAL_ASSIGNMENT")
        elif isinstance(top, ast.AnnAssign):
            if top.annotation is not None:
                raise ProducerReplayError("PRODUCER_TOP_LEVEL_ANNOTATION_FORBIDDEN")
            if top.value is not None and not _immutable_literal_only(top.value):
                raise ProducerReplayError("PRODUCER_TOP_LEVEL_MUTABLE_OR_NONLITERAL_ASSIGNMENT")
        elif isinstance(top, ast.Expr) and isinstance(top.value, ast.Constant) and isinstance(top.value.value, str):
            pass
        else:
            raise ProducerReplayError("PRODUCER_TOP_LEVEL_EXECUTION_FORBIDDEN:" + top.__class__.__name__)

    if produce_defs != 1:
        raise ProducerReplayError(f"PRODUCER_ENTRYPOINT_COUNT_INVALID:{produce_defs}")

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ProducerReplayError("PRODUCER_IMPORT_FORBIDDEN")
        if isinstance(node, ast.FunctionDef):
            _function_definition_is_pure(node)
        if isinstance(node, (ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.YieldFrom)):
            raise ProducerReplayError("PRODUCER_ASYNC_OR_GENERATOR_FORBIDDEN")
        if isinstance(node, ast.While):
            raise ProducerReplayError("PRODUCER_UNBOUNDED_WHILE_FORBIDDEN")
        if isinstance(node, ast.Try) or node.__class__.__name__ == "TryStar":
            raise ProducerReplayError("PRODUCER_EXCEPTION_HANDLING_FORBIDDEN")
        if isinstance(node, (ast.ClassDef, ast.Global, ast.Nonlocal)):
            raise ProducerReplayError("PRODUCER_STATEFUL_CONSTRUCT_FORBIDDEN:" + node.__class__.__name__)
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
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
        "while_loops_allowed": False,
        "exception_handling_allowed": False,
        "function_decorators_allowed": False,
        "function_annotations_allowed": False,
        "mutable_top_level_state_allowed": False,
        "mutable_or_executable_defaults_allowed": False,
        "dunder_access_allowed": False,
        "filesystem_api_allowed": False,
        "network_api_allowed": False,
        "dynamic_import_allowed": False,
        "prohibited_data_reference_allowed": False,
        "max_source_bytes": MAX_PRODUCER_SOURCE_BYTES,
        "max_range_items": MAX_RANGE_ITEMS,
        "max_execution_line_events": MAX_EXECUTION_LINE_EVENTS,
        "source_policy_pass": True,
    }


def _walk_input(
    value: Any,
    *,
    cutoff: int,
    path: str = "input",
    depth: int = 0,
    counter: Optional[List[int]] = None,
) -> None:
    if counter is None:
        counter = [0]
    counter[0] += 1
    if counter[0] > MAX_INPUT_NODES_PER_FIXTURE:
        raise ProducerReplayError("FIXTURE_INPUT_NODE_LIMIT_EXCEEDED")
    if depth > MAX_INPUT_DEPTH:
        raise ProducerReplayError("FIXTURE_INPUT_DEPTH_LIMIT_EXCEEDED:" + path)
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProducerReplayError("FIXTURE_NONFINITE_NUMBER:" + path)
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            _walk_input(item, cutoff=cutoff, path=f"{path}[{i}]", depth=depth + 1, counter=counter)
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
        _walk_input(child, cutoff=cutoff, path=path + "." + raw_key, depth=depth + 1, counter=counter)


def load_fixtures(path: Path) -> List[Dict[str, Any]]:
    path = Path(path).resolve()
    if not path.is_file():
        raise ProducerReplayError("FIXTURE_FILE_MISSING")
    if path.stat().st_size <= 0 or path.stat().st_size > MAX_FIXTURE_FILE_BYTES:
        raise ProducerReplayError("FIXTURE_FILE_SIZE_INVALID")
    rows: List[Dict[str, Any]] = []
    seen = set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if len(rows) >= MAX_FIXTURE_COUNT:
            raise ProducerReplayError("FIXTURE_COUNT_LIMIT_EXCEEDED")
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
    safe_builtins["range"] = _safe_range
    namespace: Dict[str, Any] = {
        "__name__": "r7_causal_producer_candidate",
        "__builtins__": safe_builtins,
        "math": math,
    }
    try:
        code = compile(source, str(path), "exec")
        exec(code, namespace, namespace)
    except ProducerReplayError:
        raise
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


def _execute_with_budget(fn, candidate_input: Dict[str, Any], fixture_id: str):
    events = [0]

    def tracer(frame, event, arg):
        if event in ("call", "line"):
            events[0] += 1
            if events[0] > MAX_EXECUTION_LINE_EVENTS:
                raise ProducerReplayError("PRODUCER_EXECUTION_BUDGET_EXCEEDED:" + fixture_id)
        return tracer

    previous = sys.gettrace()
    sys.settrace(tracer)
    try:
        return fn(candidate_input)
    finally:
        sys.settrace(previous)


def _canonical_stream_bytes(rows: List[Dict[str, Any]]) -> bytes:
    text = "\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows) + "\n"
    return text.encode("utf-8")


def _replay_producer_inprocess(fixture_path: Path, producer_module_path: Path) -> Tuple[bytes, Dict[str, Any]]:
    """Trusted worker implementation. Production callers use replay_producer(), which runs this in a child process."""
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
                result = _execute_with_budget(fn, candidate_input, row["fixture_id"])
            except ProducerReplayError:
                raise
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
    if len(stream_bytes) > MAX_REPLAY_STREAM_BYTES:
        raise ProducerReplayError("PRODUCER_STREAM_SIZE_LIMIT_EXCEEDED")
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
        "while_loops_allowed": False,
        "exception_handling_allowed": False,
        "function_decorators_allowed": False,
        "function_annotations_allowed": False,
        "mutable_top_level_state_allowed": False,
        "mutable_or_executable_defaults_allowed": False,
        "dunder_access_allowed": False,
        "filesystem_api_allowed": False,
        "network_api_allowed": False,
        "dynamic_import_allowed": False,
        "range_is_bounded": True,
        "execution_line_budget_enforced": True,
        "max_fixture_count": MAX_FIXTURE_COUNT,
        "max_input_depth": MAX_INPUT_DEPTH,
        "max_input_nodes_per_fixture": MAX_INPUT_NODES_PER_FIXTURE,
        "max_range_items": MAX_RANGE_ITEMS,
        "max_execution_line_events": MAX_EXECUTION_LINE_EVENTS,
        "future_rows_available_to_producer": False,
        "outcome_columns_present": False,
        "final_holdout_accessed": False,
        "strategy_retuned": False,
    }
    return stream_bytes, report


def _worker_error(stderr: str, returncode: int) -> ProducerReplayError:
    lines = [line.strip() for line in str(stderr or "").splitlines() if line.strip()]
    for line in reversed(lines):
        prefix = "PRODUCER_WORKER_REPLAY_ERROR:"
        if line.startswith(prefix):
            return ProducerReplayError(line[len(prefix):])
    return ProducerReplayError("PRODUCER_REPLAY_WORKER_FAILED:exit=" + str(returncode))


def replay_producer(fixture_path: Path, producer_module_path: Path) -> Tuple[bytes, Dict[str, Any]]:
    fixture_path = Path(fixture_path).resolve()
    producer_module_path = Path(producer_module_path).resolve()

    fixtures = load_fixtures(fixture_path)
    source_policy = verify_producer_source_policy(producer_module_path)
    fixture_hash_before = sha256_file(fixture_path)
    producer_hash_before = sha256_file(producer_module_path)
    worker_path = Path(__file__).with_name("r6_producer_worker.py").resolve()
    if not worker_path.is_file():
        raise ProducerReplayError("PRODUCER_REPLAY_WORKER_MISSING")
    worker_hash_before = sha256_file(worker_path)
    package_root = Path(__file__).resolve().parents[1]

    with tempfile.TemporaryDirectory(prefix="xau_r7_r1_replay_") as td:
        tmp = Path(td)
        stream_path = tmp / "producer_stream.jsonl"
        report_path = tmp / "producer_report.json"
        command = [
            sys.executable,
            "-m",
            "r7_runtime.r6_producer_worker",
            "--fixtures",
            str(fixture_path),
            "--producer-module",
            str(producer_module_path),
            "--stream-output",
            str(stream_path),
            "--report-output",
            str(report_path),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=str(package_root),
                capture_output=True,
                text=True,
                timeout=MAX_REPLAY_WALL_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProducerReplayError("PRODUCER_REPLAY_WALL_TIMEOUT") from exc
        except Exception as exc:
            raise ProducerReplayError("PRODUCER_REPLAY_WORKER_START_FAILED:" + exc.__class__.__name__) from exc
        if completed.returncode != 0:
            raise _worker_error(completed.stderr, completed.returncode)
        if not stream_path.is_file() or not report_path.is_file():
            raise ProducerReplayError("PRODUCER_REPLAY_WORKER_OUTPUT_MISSING")
        if stream_path.stat().st_size <= 0 or stream_path.stat().st_size > MAX_REPLAY_STREAM_BYTES:
            raise ProducerReplayError("PRODUCER_REPLAY_WORKER_STREAM_SIZE_INVALID")
        if report_path.stat().st_size <= 0 or report_path.stat().st_size > MAX_REPLAY_REPORT_BYTES:
            raise ProducerReplayError("PRODUCER_REPLAY_WORKER_REPORT_SIZE_INVALID")
        stream_bytes = stream_path.read_bytes()
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ProducerReplayError("PRODUCER_REPLAY_WORKER_REPORT_INVALID") from exc

    if sha256_file(fixture_path) != fixture_hash_before:
        raise ProducerReplayError("FIXTURE_FILE_CHANGED_DURING_REPLAY")
    if sha256_file(producer_module_path) != producer_hash_before:
        raise ProducerReplayError("PRODUCER_SOURCE_CHANGED_DURING_REPLAY")
    if sha256_file(worker_path) != worker_hash_before:
        raise ProducerReplayError("PRODUCER_REPLAY_WORKER_CHANGED_DURING_REPLAY")
    if not isinstance(report, dict):
        raise ProducerReplayError("PRODUCER_REPLAY_WORKER_REPORT_INVALID")
    if report.get("replay_version") != REPLAY_VERSION:
        raise ProducerReplayError("PRODUCER_REPLAY_VERSION_MISMATCH")
    if report.get("source_policy_version") != SOURCE_POLICY_VERSION:
        raise ProducerReplayError("PRODUCER_SOURCE_POLICY_VERSION_MISMATCH")
    if report.get("fixture_file_sha256") != fixture_hash_before:
        raise ProducerReplayError("PRODUCER_REPLAY_FIXTURE_HASH_MISMATCH")
    if report.get("producer_module_sha256") != producer_hash_before:
        raise ProducerReplayError("PRODUCER_REPLAY_SOURCE_HASH_MISMATCH")
    if report.get("fixture_count") != len(fixtures):
        raise ProducerReplayError("PRODUCER_REPLAY_FIXTURE_COUNT_MISMATCH")
    if report.get("source_policy_pass") is not True or source_policy.get("source_policy_pass") is not True:
        raise ProducerReplayError("PRODUCER_SOURCE_POLICY_NOT_PASS")
    if report.get("producer_stream_sha256") != hashlib.sha256(stream_bytes).hexdigest():
        raise ProducerReplayError("PRODUCER_REPLAY_STREAM_HASH_MISMATCH")

    report = dict(report)
    report.update({
        "process_isolation_enforced": True,
        "worker_module_sha256": worker_hash_before,
        "wall_timeout_seconds": MAX_REPLAY_WALL_SECONDS,
    })
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
    parser = argparse.ArgumentParser(description="Replay an import-free resource-bounded R6 causal producer in an isolated timed worker process")
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
