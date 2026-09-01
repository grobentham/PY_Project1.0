from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from r7_runtime.constants import CANONICAL_R6_ZIP_SHA256
from r7_runtime.r6_integrity import sha256_file
from r7_runtime.r6_producer_replay import (
    MAX_EXECUTION_LINE_EVENTS,
    MAX_FIXTURE_COUNT,
    MAX_INPUT_DEPTH,
    MAX_INPUT_NODES_PER_FIXTURE,
    MAX_RANGE_ITEMS,
    MAX_REPLAY_WALL_SECONDS,
    REPLAY_VERSION,
    SOURCE_POLICY_VERSION,
)
from r7_runtime.r6_producer_seal import (
    ALLOWED_CANDIDATE_FILES,
    GENERATED_SEAL_FILENAME,
    PRODUCER_MODULE_RELATIVE,
    SEAL_VERSION,
    ProducerSealError,
    seal_candidate,
)


class ProducerSealTests(unittest.TestCase):
    def build_baseline(self, root: Path, *, producer_ready: bool = False):
        protected = {}
        for relative, text in {
            "v16r6/engine.py": "R6='frozen'\n",
            "v16r5/engine.py": "R5='frozen'\n",
            "V16_R5_MAIN.py": "MAIN='frozen'\n",
        }.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            protected[relative] = sha256_file(path)
        parent = {
            "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
            "build_verified_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
            "protected_r6_hashes": protected,
            "final_holdout_accessed": False,
            "strategy_retuned": False,
            "causal_r6_producer_ready": producer_ready,
        }
        (root / "R7_R1_PARENT_INTEGRITY.json").write_text(json.dumps(parent), encoding="utf-8")
        return protected

    def build_candidate(self, root: Path):
        for relative in sorted(ALLOWED_CANDIDATE_FILES):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if relative.endswith(".json") or relative.endswith(".jsonl"):
                path.write_text("{}\n", encoding="utf-8")
            else:
                path.write_text('def produce(prefix):\n    return prefix.get("decision")\n', encoding="utf-8")

    @staticmethod
    def security_contract():
        return {
            "replay_version": REPLAY_VERSION,
            "source_policy_version": SOURCE_POLICY_VERSION,
            "process_isolation_enforced": True,
            "worker_module_sha256": "a" * 64,
            "wall_timeout_seconds": MAX_REPLAY_WALL_SECONDS,
            "max_fixture_count": MAX_FIXTURE_COUNT,
            "max_input_depth": MAX_INPUT_DEPTH,
            "max_input_nodes_per_fixture": MAX_INPUT_NODES_PER_FIXTURE,
            "max_range_items": MAX_RANGE_ITEMS,
            "max_execution_line_events": MAX_EXECUTION_LINE_EVENTS,
        }

    def admission(self):
        return {
            "admission_version": "TEST_ADMISSION_V4",
            "authority_version": "TEST_AUTHORITY_V5",
            "ready": True,
            "trusted_replay_security_contract_pass": True,
            "trusted_replay_security_contract": self.security_contract(),
            "canonical_reference_replay_pass": True,
            "canonical_reference_replay": {
                "reference_generated_by_exact_canonical_source_executor": True,
                "final_holdout_accessed": False,
                "strategy_retuned": False,
            },
            "trusted_replay": {"deterministic_double_run": True},
            "parity": {
                "trusted_producer_replay_pass": True,
                "producer_source_policy_pass": True,
            },
            "final_holdout_accessed": False,
            "strategy_retuned": False,
        }

    def make_roots(self, td: str):
        base = Path(td) / "baseline"
        candidate = Path(td) / "candidate"
        base.mkdir(); candidate.mkdir()
        self.build_baseline(base)
        self.build_candidate(candidate)
        return base, candidate

    def test_valid_candidate_is_sealed_in_isolated_copy_without_baseline_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "baseline"
            candidate = Path(td) / "candidate"
            base.mkdir(); candidate.mkdir()
            protected = self.build_baseline(base)
            self.build_candidate(candidate)
            before_parent = sha256_file(base / "R7_R1_PARENT_INTEGRITY.json")
            with mock.patch("r7_runtime.r6_producer_seal.verify_producer_admission", return_value=self.admission()) as verify:
                result = seal_candidate(base, candidate)
            self.assertEqual(result["seal_version"], SEAL_VERSION)
            self.assertTrue(result["admission_ready"])
            self.assertTrue(result["trusted_replay_security_contract_pass"])
            self.assertEqual(result["trusted_replay_security_contract"], self.security_contract())
            self.assertTrue(result["canonical_reference_replay_pass"])
            self.assertEqual(result["authority_version"], "TEST_AUTHORITY_V5")
            self.assertTrue(result["trusted_producer_replay_pass"])
            self.assertTrue(result["producer_source_policy_pass"])
            self.assertFalse(result["baseline_mutated"])
            self.assertFalse(result["execution_unlocked"])
            self.assertEqual(result["producer_module"], PRODUCER_MODULE_RELATIVE)
            self.assertEqual(result["producer_module_sha256"], sha256_file(candidate / PRODUCER_MODULE_RELATIVE))
            self.assertEqual(result["fixture_corpus_sha256"], sha256_file(candidate / "R7_R1_R6_PARITY_FIXTURES.jsonl"))
            self.assertEqual(result["producer_replay_attestation_sha256"], sha256_file(candidate / "R7_R1_R6_PRODUCER_REPLAY.json"))
            self.assertEqual(result["reference_stream_sha256"], sha256_file(candidate / "R7_R1_R6_REFERENCE_STREAM.jsonl"))
            self.assertEqual(result["reference_replay_attestation_sha256"], sha256_file(candidate / "R7_R1_R6_REFERENCE_REPLAY.json"))
            self.assertEqual(sha256_file(base / "R7_R1_PARENT_INTEGRITY.json"), before_parent)
            for relative, digest in protected.items():
                self.assertEqual(sha256_file(base / relative), digest)
            verify.assert_called_once()
            self.assertNotEqual(Path(verify.call_args.args[0]), base)

    def test_existing_generated_seal_is_ignored_for_repeatable_reseal(self):
        with tempfile.TemporaryDirectory() as td:
            base, candidate = self.make_roots(td)
            old_seal = candidate / GENERATED_SEAL_FILENAME
            old_seal.write_text('{"old":true}\n', encoding="utf-8")
            with mock.patch("r7_runtime.r6_producer_seal.verify_producer_admission", return_value=self.admission()):
                result = seal_candidate(base, candidate)
            self.assertNotIn(GENERATED_SEAL_FILENAME, result["candidate_files_sha256"])
            self.assertTrue(old_seal.is_file())

    def test_unexpected_candidate_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            base, candidate = self.make_roots(td)
            (candidate / "secret.csv").write_text("outcome\n999\n", encoding="utf-8")
            with self.assertRaisesRegex(ProducerSealError, "CANDIDATE_UNEXPECTED_FILES"):
                seal_candidate(base, candidate)

    def test_missing_reference_replay_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            base, candidate = self.make_roots(td)
            (candidate / "R7_R1_R6_REFERENCE_REPLAY.json").unlink()
            with self.assertRaisesRegex(ProducerSealError, "CANDIDATE_REQUIRED_FILES_MISSING"):
                seal_candidate(base, candidate)

    def test_failed_admission_cannot_be_sealed(self):
        with tempfile.TemporaryDirectory() as td:
            base, candidate = self.make_roots(td)
            with mock.patch("r7_runtime.r6_producer_seal.verify_producer_admission", side_effect=RuntimeError("CANONICAL_REFERENCE_REPLAY_FAILED")):
                with self.assertRaisesRegex(ProducerSealError, "CANDIDATE_ADMISSION_FAILED:CANONICAL_REFERENCE_REPLAY_FAILED"):
                    seal_candidate(base, candidate)

    def test_missing_replay_security_contract_cannot_be_sealed(self):
        with tempfile.TemporaryDirectory() as td:
            base, candidate = self.make_roots(td)
            bad = self.admission(); bad["trusted_replay_security_contract_pass"] = False
            with mock.patch("r7_runtime.r6_producer_seal.verify_producer_admission", return_value=bad):
                with self.assertRaisesRegex(ProducerSealError, "CANDIDATE_REPLAY_SECURITY_CONTRACT_NOT_PROVEN"):
                    seal_candidate(base, candidate)

    def test_replay_process_isolation_cannot_be_downgraded(self):
        with tempfile.TemporaryDirectory() as td:
            base, candidate = self.make_roots(td)
            bad = self.admission(); bad["trusted_replay_security_contract"] = dict(self.security_contract())
            bad["trusted_replay_security_contract"]["process_isolation_enforced"] = False
            with mock.patch("r7_runtime.r6_producer_seal.verify_producer_admission", return_value=bad):
                with self.assertRaisesRegex(ProducerSealError, "CANDIDATE_REPLAY_PROCESS_ISOLATION_NOT_PROVEN"):
                    seal_candidate(base, candidate)

    def test_admission_without_canonical_reference_proof_cannot_be_sealed(self):
        with tempfile.TemporaryDirectory() as td:
            base, candidate = self.make_roots(td)
            bad = self.admission(); bad["canonical_reference_replay_pass"] = False
            with mock.patch("r7_runtime.r6_producer_seal.verify_producer_admission", return_value=bad):
                with self.assertRaisesRegex(ProducerSealError, "CANDIDATE_CANONICAL_REFERENCE_REPLAY_NOT_PROVEN"):
                    seal_candidate(base, candidate)

    def test_admission_without_exact_reference_executor_claim_cannot_be_sealed(self):
        with tempfile.TemporaryDirectory() as td:
            base, candidate = self.make_roots(td)
            bad = self.admission(); bad["canonical_reference_replay"] = dict(bad["canonical_reference_replay"])
            bad["canonical_reference_replay"]["reference_generated_by_exact_canonical_source_executor"] = False
            with mock.patch("r7_runtime.r6_producer_seal.verify_producer_admission", return_value=bad):
                with self.assertRaisesRegex(ProducerSealError, "CANDIDATE_CANONICAL_REFERENCE_EXECUTOR_NOT_PROVEN"):
                    seal_candidate(base, candidate)

    def test_admission_without_replay_proof_cannot_be_sealed(self):
        with tempfile.TemporaryDirectory() as td:
            base, candidate = self.make_roots(td)
            bad = self.admission(); bad["trusted_replay"] = {"deterministic_double_run": False}
            with mock.patch("r7_runtime.r6_producer_seal.verify_producer_admission", return_value=bad):
                with self.assertRaisesRegex(ProducerSealError, "CANDIDATE_TRUSTED_REPLAY_NOT_PROVEN"):
                    seal_candidate(base, candidate)

    def test_baseline_with_readiness_already_flipped_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "baseline"; candidate = Path(td) / "candidate"
            base.mkdir(); candidate.mkdir(); self.build_baseline(base, producer_ready=True); self.build_candidate(candidate)
            with self.assertRaisesRegex(ProducerSealError, "BASELINE_MUST_REMAIN_PRODUCER_LOCKED"):
                seal_candidate(base, candidate)


if __name__ == "__main__":
    unittest.main()
