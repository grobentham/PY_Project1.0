from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from producer_fixture_support import build_trusted_fixture
from r7_runtime.r6_admission_authority import (
    AUTHORITY_VERSION,
    ProducerAdmissionAuthorityError,
    producer_admission_status,
    verify_producer_admission,
)
from r7_runtime.r6_reference_replay import replay_canonical_reference


class ProducerAdmissionAuthorityTests(unittest.TestCase):
    def prepare(self, root: Path):
        paths = build_trusted_fixture(root)
        original_reference_bytes = paths["reference"].read_bytes()

        def exact_executor(source_root: Path, fixture_path: Path) -> bytes:
            return original_reference_bytes

        stream, attestation = replay_canonical_reference(
            root,
            paths["bundle"],
            paths["fixtures"],
            _executor=exact_executor,
        )
        paths["reference"].write_bytes(stream)
        reference_replay = root / "R7_R1_R6_REFERENCE_REPLAY.json"
        reference_replay.write_text(
            json.dumps(attestation, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        paths["reference_replay"] = reference_replay
        return paths, exact_executor

    def test_production_authority_fails_closed_without_exact_source_executor(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.prepare(root)
            with self.assertRaisesRegex(
                ProducerAdmissionAuthorityError,
                "CANONICAL_REFERENCE_EXECUTOR_NOT_IMPLEMENTED_FROM_EXACT_R6_SOURCE",
            ):
                verify_producer_admission(root)

    def test_exact_reference_replay_plus_v4_candidate_evidence_can_pass_v5_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths, exact_executor = self.prepare(root)
            result = verify_producer_admission(root, _reference_executor=exact_executor)
            self.assertEqual(result["authority_version"], AUTHORITY_VERSION)
            self.assertTrue(result["ready"])
            self.assertTrue(result["trusted_replay_security_contract_pass"])
            self.assertTrue(result["trusted_replay_security_contract"]["process_isolation_enforced"])
            self.assertEqual(len(result["trusted_replay_security_contract"]["worker_module_sha256"]), 64)
            self.assertTrue(result["canonical_reference_replay_pass"])
            self.assertTrue(
                result["canonical_reference_replay"][
                    "reference_generated_by_exact_canonical_source_executor"
                ]
            )
            self.assertEqual(
                result["canonical_reference_replay"]["reference_stream_sha256"],
                result["parity"]["reference_stream_sha256"],
            )
            self.assertFalse(result["final_holdout_accessed"])
            self.assertFalse(result["strategy_retuned"])
            self.assertTrue(paths["reference_replay"].is_file())

    def test_downgraded_process_isolation_cannot_pass_v5_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, exact_executor = self.prepare(root)
            good = verify_producer_admission(root, _reference_executor=exact_executor)
            downgraded = dict(good)
            replay = dict(good["trusted_replay"])
            replay["process_isolation_enforced"] = False
            downgraded["trusted_replay"] = replay
            with mock.patch(
                "r7_runtime.r6_admission_authority.verify_v4_candidate_admission",
                return_value=downgraded,
            ):
                with self.assertRaisesRegex(
                    ProducerAdmissionAuthorityError,
                    "TRUSTED_REPLAY_REQUIRED_GUARD_MISSING:process_isolation_enforced",
                ):
                    verify_producer_admission(root, _reference_executor=exact_executor)

    def test_downgraded_replay_version_cannot_pass_v5_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, exact_executor = self.prepare(root)
            good = verify_producer_admission(root, _reference_executor=exact_executor)
            downgraded = dict(good)
            replay = dict(good["trusted_replay"])
            replay["replay_version"] = "R7_R1_R6_PRODUCER_REPLAY_V3"
            downgraded["trusted_replay"] = replay
            with mock.patch(
                "r7_runtime.r6_admission_authority.verify_v4_candidate_admission",
                return_value=downgraded,
            ):
                with self.assertRaisesRegex(
                    ProducerAdmissionAuthorityError,
                    "TRUSTED_REPLAY_VERSION_MISMATCH",
                ):
                    verify_producer_admission(root, _reference_executor=exact_executor)

    def test_supplied_reference_changed_after_attestation_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths, exact_executor = self.prepare(root)
            paths["reference"].write_text('{"tampered":true}\n', encoding="utf-8")
            with self.assertRaisesRegex(
                ProducerAdmissionAuthorityError,
                "REFERENCE_STREAM_NOT_CANONICAL_REPLAY_OUTPUT",
            ):
                verify_producer_admission(root, _reference_executor=exact_executor)

    def test_reference_attestation_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths, exact_executor = self.prepare(root)
            attestation = json.loads(paths["reference_replay"].read_text(encoding="utf-8"))
            attestation["strategy_retuned"] = True
            paths["reference_replay"].write_text(json.dumps(attestation), encoding="utf-8")
            with self.assertRaisesRegex(
                ProducerAdmissionAuthorityError,
                "REFERENCE_REPLAY_ATTESTATION_MISMATCH",
            ):
                verify_producer_admission(root, _reference_executor=exact_executor)

    def test_status_is_not_ready_in_production_until_exact_executor_exists(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.prepare(root)
            status = producer_admission_status(root)
            self.assertFalse(status["ready"])
            self.assertEqual(status["authority_version"], AUTHORITY_VERSION)
            self.assertFalse(status["trusted_replay_security_contract_pass"])
            self.assertFalse(status["canonical_reference_replay_pass"])
            self.assertIn("CANONICAL_REFERENCE_EXECUTOR_NOT_IMPLEMENTED", status["reason"])
            self.assertFalse(status["final_holdout_accessed"])
            self.assertFalse(status["strategy_retuned"])


if __name__ == "__main__":
    unittest.main()
