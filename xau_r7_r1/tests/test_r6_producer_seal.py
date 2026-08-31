from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from r7_runtime.constants import CANONICAL_R6_ZIP_SHA256
from r7_runtime.r6_integrity import sha256_file
from r7_runtime.r6_producer_seal import (
    ALLOWED_CANDIDATE_FILES,
    PRODUCER_MODULE_RELATIVE,
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
            if relative.endswith(".json"):
                path.write_text("{}\n", encoding="utf-8")
            elif relative.endswith(".jsonl"):
                path.write_text("{}\n", encoding="utf-8")
            else:
                path.write_text("def produce(prefix):\n    return prefix\n", encoding="utf-8")

    def test_valid_candidate_is_sealed_in_isolated_copy_without_baseline_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "baseline"
            candidate = Path(td) / "candidate"
            base.mkdir(); candidate.mkdir()
            protected = self.build_baseline(base)
            self.build_candidate(candidate)
            before_parent = sha256_file(base / "R7_R1_PARENT_INTEGRITY.json")

            admission = {
                "admission_version": "TEST_ADMISSION",
                "ready": True,
                "final_holdout_accessed": False,
                "strategy_retuned": False,
            }
            with mock.patch("r7_runtime.r6_producer_seal.verify_producer_admission", return_value=admission) as verify:
                result = seal_candidate(base, candidate)

            self.assertTrue(result["admission_ready"])
            self.assertFalse(result["baseline_mutated"])
            self.assertFalse(result["execution_unlocked"])
            self.assertEqual(result["producer_module"], PRODUCER_MODULE_RELATIVE)
            self.assertEqual(result["producer_module_sha256"], sha256_file(candidate / PRODUCER_MODULE_RELATIVE))
            self.assertEqual(sha256_file(base / "R7_R1_PARENT_INTEGRITY.json"), before_parent)
            for relative, digest in protected.items():
                self.assertEqual(sha256_file(base / relative), digest)
            verify.assert_called_once()
            staging_root = Path(verify.call_args.args[0])
            self.assertNotEqual(staging_root, base)

    def test_unexpected_candidate_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "baseline"
            candidate = Path(td) / "candidate"
            base.mkdir(); candidate.mkdir()
            self.build_baseline(base)
            self.build_candidate(candidate)
            (candidate / "secret.csv").write_text("outcome\n999\n", encoding="utf-8")
            with self.assertRaisesRegex(ProducerSealError, "CANDIDATE_UNEXPECTED_FILES"):
                seal_candidate(base, candidate)

    def test_missing_candidate_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "baseline"
            candidate = Path(td) / "candidate"
            base.mkdir(); candidate.mkdir()
            self.build_baseline(base)
            self.build_candidate(candidate)
            (candidate / "R7_R1_R6_PRODUCER_PARITY.json").unlink()
            with self.assertRaisesRegex(ProducerSealError, "CANDIDATE_REQUIRED_FILES_MISSING"):
                seal_candidate(base, candidate)

    def test_failed_admission_cannot_be_sealed(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "baseline"
            candidate = Path(td) / "candidate"
            base.mkdir(); candidate.mkdir()
            self.build_baseline(base)
            self.build_candidate(candidate)
            with mock.patch(
                "r7_runtime.r6_producer_seal.verify_producer_admission",
                side_effect=RuntimeError("PARITY_MISMATCH"),
            ):
                with self.assertRaisesRegex(ProducerSealError, "CANDIDATE_ADMISSION_FAILED:PARITY_MISMATCH"):
                    seal_candidate(base, candidate)

    def test_baseline_with_readiness_already_flipped_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "baseline"
            candidate = Path(td) / "candidate"
            base.mkdir(); candidate.mkdir()
            self.build_baseline(base, producer_ready=True)
            self.build_candidate(candidate)
            with self.assertRaisesRegex(ProducerSealError, "BASELINE_MUST_REMAIN_PRODUCER_LOCKED"):
                seal_candidate(base, candidate)


if __name__ == "__main__":
    unittest.main()
