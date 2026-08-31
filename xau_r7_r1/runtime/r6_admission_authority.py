from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .constants import CANONICAL_R6_ZIP_SHA256
from .r6_integrity import sha256_file
from .r6_producer_admission import verify_producer_admission as verify_v4_candidate_admission
from .r6_reference_replay import (
    ReferenceExecutor,
    ReferenceReplayError,
    verify_reference_replay_evidence,
)


class ProducerAdmissionAuthorityError(RuntimeError):
    pass


AUTHORITY_VERSION = "R7_R1_R6_PRODUCER_ADMISSION_AUTHORITY_V5"


def verify_producer_admission(
    root: Path,
    *,
    _reference_executor: Optional[ReferenceExecutor] = None,
) -> Dict[str, Any]:
    """Authoritative producer admission.

    V4 candidate admission proves the candidate module generated its producer
    stream and matches a supplied reference stream. V5 adds the independent
    authority boundary: the reference stream itself must be regenerated from
    the exact canonical frozen R6 source bundle. The production executor is
    deliberately unavailable until that exact-source adapter is implemented,
    so production admission remains fail-closed rather than trusting a supplied
    reference stream.
    """
    root = Path(root).resolve()
    source_bundle_manifest_path = root / "R7_R1_R6_SOURCE_BUNDLE_MANIFEST.json"
    fixture_path = root / "R7_R1_R6_PARITY_FIXTURES.jsonl"
    reference_stream_path = root / "R7_R1_R6_REFERENCE_STREAM.jsonl"
    reference_attestation_path = root / "R7_R1_R6_REFERENCE_REPLAY.json"

    try:
        reference = verify_reference_replay_evidence(
            root,
            source_bundle_manifest_path,
            fixture_path,
            reference_stream_path,
            reference_attestation_path,
            _executor=_reference_executor,
        )
    except ReferenceReplayError as exc:
        raise ProducerAdmissionAuthorityError("CANONICAL_REFERENCE_REPLAY_FAILED:" + str(exc)) from exc

    try:
        candidate = verify_v4_candidate_admission(root)
    except Exception as exc:
        raise ProducerAdmissionAuthorityError("V4_CANDIDATE_ADMISSION_FAILED:" + str(exc)) from exc
    if candidate.get("ready") is not True:
        raise ProducerAdmissionAuthorityError("V4_CANDIDATE_ADMISSION_NOT_READY")
    if candidate.get("canonical_parent_zip_sha256") != CANONICAL_R6_ZIP_SHA256:
        raise ProducerAdmissionAuthorityError("V4_CANDIDATE_PARENT_SHA_MISMATCH")
    if candidate.get("final_holdout_accessed") is not False:
        raise ProducerAdmissionAuthorityError("V4_CANDIDATE_HOLDOUT_BOUNDARY_BREACH")
    if candidate.get("strategy_retuned") is not False:
        raise ProducerAdmissionAuthorityError("V4_CANDIDATE_RETUNING_BREACH")

    parity = candidate.get("parity")
    if not isinstance(parity, dict) or parity.get("parity_pass") is not True:
        raise ProducerAdmissionAuthorityError("V4_CANDIDATE_PARITY_NOT_PASS")
    if parity.get("reference_stream_sha256") != sha256_file(reference_stream_path):
        raise ProducerAdmissionAuthorityError("REFERENCE_STREAM_NOT_BOUND_TO_PARITY")
    if parity.get("fixture_corpus_sha256") != reference.get("fixture_file_sha256"):
        raise ProducerAdmissionAuthorityError("REFERENCE_FIXTURE_NOT_BOUND_TO_PARITY")
    if parity.get("source_bundle_manifest_sha256") != reference.get("source_bundle_manifest_sha256"):
        raise ProducerAdmissionAuthorityError("REFERENCE_SOURCE_BUNDLE_NOT_BOUND_TO_PARITY")

    return {
        **candidate,
        "authority_version": AUTHORITY_VERSION,
        "ready": True,
        "canonical_reference_replay": reference,
        "canonical_reference_replay_pass": True,
        "reference_attestation_sha256": sha256_file(reference_attestation_path),
        "final_holdout_accessed": False,
        "strategy_retuned": False,
    }


def producer_admission_status(root: Path) -> Dict[str, Any]:
    try:
        return verify_producer_admission(root)
    except Exception as exc:
        return {
            "authority_version": AUTHORITY_VERSION,
            "ready": False,
            "reason": str(exc),
            "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
            "canonical_reference_replay_pass": False,
            "final_holdout_accessed": False,
            "strategy_retuned": False,
        }
