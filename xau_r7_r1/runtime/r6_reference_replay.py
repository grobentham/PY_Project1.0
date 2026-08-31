from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from .constants import CANONICAL_R6_ZIP_SHA256
from .r6_integrity import sha256_file
from .r6_producer_replay import FIXTURE_SCHEMA, load_fixtures
from .r6_source_bundle import BUNDLE_VERSION


class ReferenceReplayError(RuntimeError):
    pass


REFERENCE_REPLAY_VERSION = "R7_R1_R6_CANONICAL_REFERENCE_REPLAY_V1"
REFERENCE_EXECUTOR_VERSION = "R7_R1_R6_CANONICAL_REFERENCE_EXECUTOR_V1"

ReferenceExecutor = Callable[[Path, Path], bytes]


def _canonicalize_stream_bytes(raw: bytes) -> bytes:
    try:
        text = raw.decode("utf-8")
    except Exception as exc:
        raise ReferenceReplayError("REFERENCE_EXECUTOR_OUTPUT_NOT_UTF8") from exc
    lines = text.splitlines()
    if not lines:
        raise ReferenceReplayError("REFERENCE_EXECUTOR_OUTPUT_EMPTY")
    canonical = []
    for line_no, line in enumerate(lines, 1):
        if not line.strip():
            raise ReferenceReplayError(f"REFERENCE_EXECUTOR_BLANK_LINE:{line_no}")
        try:
            row = json.loads(line)
        except Exception as exc:
            raise ReferenceReplayError(f"REFERENCE_EXECUTOR_BAD_JSON:{line_no}") from exc
        if not isinstance(row, dict):
            raise ReferenceReplayError(f"REFERENCE_EXECUTOR_RECORD_INVALID:{line_no}")
        if set(row) != {"fixture_id", "available_through_ms", "decision"}:
            raise ReferenceReplayError(f"REFERENCE_EXECUTOR_RECORD_SCHEMA_MISMATCH:{line_no}")
        canonical.append(json.dumps(row, sort_keys=True, separators=(",", ":")))
    return ("\n".join(canonical) + "\n").encode("utf-8")


def _verify_source_bundle_identity(source_root: Path, source_bundle_manifest_path: Path) -> Dict[str, Any]:
    source_root = Path(source_root).resolve()
    manifest_path = Path(source_bundle_manifest_path).resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ReferenceReplayError("REFERENCE_SOURCE_BUNDLE_MANIFEST_UNREADABLE") from exc
    if not isinstance(manifest, dict):
        raise ReferenceReplayError("REFERENCE_SOURCE_BUNDLE_MANIFEST_INVALID")
    if manifest.get("bundle_version") != BUNDLE_VERSION:
        raise ReferenceReplayError("REFERENCE_SOURCE_BUNDLE_VERSION_MISMATCH")
    if manifest.get("canonical_parent_zip_sha256") != CANONICAL_R6_ZIP_SHA256:
        raise ReferenceReplayError("REFERENCE_SOURCE_BUNDLE_PARENT_SHA_MISMATCH")
    if manifest.get("source_only_bundle") is not True:
        raise ReferenceReplayError("REFERENCE_SOURCE_BUNDLE_NOT_SOURCE_ONLY")
    if manifest.get("static_local_python_dependency_closure_extracted") is not True:
        raise ReferenceReplayError("REFERENCE_SOURCE_BUNDLE_CLOSURE_NOT_PROVEN")
    if manifest.get("required_local_imports_resolved") is not True:
        raise ReferenceReplayError("REFERENCE_SOURCE_BUNDLE_LOCAL_IMPORTS_UNRESOLVED")
    if manifest.get("dynamic_imports_allowed") is not False:
        raise ReferenceReplayError("REFERENCE_SOURCE_BUNDLE_DYNAMIC_IMPORTS_ALLOWED")
    if manifest.get("final_holdout_accessed") is not False:
        raise ReferenceReplayError("REFERENCE_SOURCE_BUNDLE_HOLDOUT_BOUNDARY_BREACH")
    if manifest.get("strategy_retuned") is not False:
        raise ReferenceReplayError("REFERENCE_SOURCE_BUNDLE_RETUNING_BREACH")

    closure = manifest.get("dependency_closure_files")
    files = manifest.get("files")
    if not isinstance(closure, list) or not isinstance(files, dict) or not closure:
        raise ReferenceReplayError("REFERENCE_SOURCE_BUNDLE_FILESET_INVALID")
    if len(closure) != len(set(str(x).replace("\\", "/") for x in closure)):
        raise ReferenceReplayError("REFERENCE_SOURCE_BUNDLE_DUPLICATE_PATH")
    for raw_relative in closure:
        relative = str(raw_relative).replace("\\", "/")
        if relative.startswith("/") or ".." in Path(relative).parts or not relative.endswith(".py"):
            raise ReferenceReplayError("REFERENCE_SOURCE_BUNDLE_PATH_INVALID:" + relative)
        lowered = relative.lower()
        if "final_holdout" in lowered or lowered.startswith("research_consumed_validation/"):
            raise ReferenceReplayError("REFERENCE_SOURCE_BUNDLE_PROHIBITED_PATH:" + relative)
        entry = files.get(relative)
        if not isinstance(entry, dict):
            raise ReferenceReplayError("REFERENCE_SOURCE_BUNDLE_FILE_ENTRY_MISSING:" + relative)
        expected = str(entry.get("sha256", "")).lower()
        actual = (source_root / relative).resolve()
        try:
            actual.relative_to(source_root)
        except ValueError as exc:
            raise ReferenceReplayError("REFERENCE_SOURCE_PATH_ESCAPE:" + relative) from exc
        if len(expected) != 64 or not actual.is_file() or sha256_file(actual) != expected:
            raise ReferenceReplayError("REFERENCE_SOURCE_FILE_HASH_MISMATCH:" + relative)
    return manifest


def execute_canonical_reference(source_root: Path, fixture_path: Path) -> bytes:
    """Production canonical reference executor.

    Deliberately fail-closed until the exact frozen R5/R6 source bodies are
    available to implement and audit their causal fixture adapter. This is a
    real authority boundary: producer admission must not treat a supplied
    reference stream as canonical merely because it is hash-bound.
    """
    raise ReferenceReplayError("CANONICAL_REFERENCE_EXECUTOR_NOT_IMPLEMENTED_FROM_EXACT_R6_SOURCE")


def replay_canonical_reference(
    source_root: Path,
    source_bundle_manifest_path: Path,
    fixture_path: Path,
    *,
    _executor: Optional[ReferenceExecutor] = None,
) -> Tuple[bytes, Dict[str, Any]]:
    source_root = Path(source_root).resolve()
    source_bundle_manifest_path = Path(source_bundle_manifest_path).resolve()
    fixture_path = Path(fixture_path).resolve()
    _verify_source_bundle_identity(source_root, source_bundle_manifest_path)
    fixtures = load_fixtures(fixture_path)
    executor = _executor or execute_canonical_reference
    try:
        raw = executor(source_root, fixture_path)
    except ReferenceReplayError:
        raise
    except Exception as exc:
        raise ReferenceReplayError("CANONICAL_REFERENCE_EXECUTOR_FAILED:" + exc.__class__.__name__) from exc
    if not isinstance(raw, (bytes, bytearray)):
        raise ReferenceReplayError("CANONICAL_REFERENCE_EXECUTOR_OUTPUT_NOT_BYTES")
    stream = _canonicalize_stream_bytes(bytes(raw))

    # Reference output must cover the exact causal fixture IDs and cutoffs.
    expected = {row["fixture_id"]: row["available_through_ms"] for row in fixtures}
    observed: Dict[str, int] = {}
    for line_no, line in enumerate(stream.decode("utf-8").splitlines(), 1):
        row = json.loads(line)
        fixture_id = row.get("fixture_id")
        cutoff = row.get("available_through_ms")
        if not isinstance(fixture_id, str) or fixture_id in observed:
            raise ReferenceReplayError(f"REFERENCE_FIXTURE_ID_INVALID:{line_no}")
        if isinstance(cutoff, bool) or not isinstance(cutoff, int):
            raise ReferenceReplayError(f"REFERENCE_CUTOFF_INVALID:{line_no}")
        observed[fixture_id] = cutoff
    if observed != expected:
        raise ReferenceReplayError("REFERENCE_FIXTURE_COVERAGE_OR_CUTOFF_MISMATCH")

    stream_hash = hashlib.sha256(stream).hexdigest()
    attestation = {
        "reference_replay_version": REFERENCE_REPLAY_VERSION,
        "reference_executor_version": REFERENCE_EXECUTOR_VERSION,
        "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
        "source_bundle_manifest_sha256": sha256_file(source_bundle_manifest_path),
        "fixture_schema": FIXTURE_SCHEMA,
        "fixture_file_sha256": sha256_file(fixture_path),
        "fixture_count": len(fixtures),
        "reference_stream_sha256": stream_hash,
        "reference_generated_by_exact_canonical_source_executor": True,
        "causal_fixture_only": True,
        "future_rows_available": False,
        "outcome_columns_available": False,
        "final_holdout_accessed": False,
        "strategy_retuned": False,
    }
    return stream, attestation


def verify_reference_replay_evidence(
    source_root: Path,
    source_bundle_manifest_path: Path,
    fixture_path: Path,
    reference_stream_path: Path,
    reference_attestation_path: Path,
    *,
    _executor: Optional[ReferenceExecutor] = None,
) -> Dict[str, Any]:
    stream, expected = replay_canonical_reference(
        source_root,
        source_bundle_manifest_path,
        fixture_path,
        _executor=_executor,
    )
    reference_stream_path = Path(reference_stream_path).resolve()
    reference_attestation_path = Path(reference_attestation_path).resolve()
    if not reference_stream_path.is_file():
        raise ReferenceReplayError("REFERENCE_STREAM_MISSING")
    if reference_stream_path.read_bytes() != stream:
        raise ReferenceReplayError("REFERENCE_STREAM_NOT_CANONICAL_REPLAY_OUTPUT")
    try:
        actual = json.loads(reference_attestation_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ReferenceReplayError("REFERENCE_REPLAY_ATTESTATION_UNREADABLE") from exc
    if not isinstance(actual, dict) or actual != expected:
        raise ReferenceReplayError("REFERENCE_REPLAY_ATTESTATION_MISMATCH")
    return expected
