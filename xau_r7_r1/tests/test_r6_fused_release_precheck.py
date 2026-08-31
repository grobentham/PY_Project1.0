from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from r7_runtime.constants import CANONICAL_R6_ZIP_SHA256
from r7_runtime.r6_fused_release_precheck import (
    FusedReleasePrecheckError,
    verify_fused_release_precheck,
)
from r7_runtime.r6_producer_seal import SEAL_VERSION


class FusedReleasePrecheckTests(unittest.TestCase):
    def build_paths(self, root: Path):
        runtime = root / "runtime"
        candidate = root / "candidate"
        runtime.mkdir(); candidate.mkdir()
        seal_path = candidate / "R7_R1_R6_PRODUCER_CANDIDATE_SEAL.json"
        return runtime, candidate, seal_path

    def good_seal(self):
        hashes = {
            "r7_runtime/r6_causal_producer.py": "1" * 64,
            "R7_R1_R6_SOURCE_PROBE.json": "2" * 64,
            "R7_R1_R6_SOURCE_BUNDLE_MANIFEST.json": "3" * 64,
            "R7_R1_R6_REFERENCE_STREAM.jsonl": "4" * 64,
            "R7_R1_R6_PRODUCER_STREAM.jsonl": "5" * 64,
            "R7_R1_R6_PARITY_ISOLATION.json": "6" * 64,
            "R7_R1_R6_PRODUCER_PARITY.json": "7" * 64,
        }
        return {
            "seal_version": SEAL_VERSION,
            "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
            "candidate_files_sha256": hashes,
            "producer_module": "r7_runtime/r6_causal_producer.py",
            "producer_module_sha256": hashes["r7_runtime/r6_causal_producer.py"],
            "admission_version": "TEST_ADMISSION_V3",
            "admission_ready": True,
            "baseline_mutated": False,
            "execution_unlocked": False,
            "final_holdout_accessed": False,
            "strategy_retuned": False,
        }

    @staticmethod
    def baseline_integrity():
        return {
            "causal_r6_producer_ready": False,
            "execution_runtime_hard_locked": True,
        }

    def test_matching_fresh_seal_only_grants_future_fused_build_eligibility(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            seal = self.good_seal()
            seal_path.write_text(json.dumps(seal), encoding="utf-8")
            with mock.patch(
                "r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity",
                return_value=self.baseline_integrity(),
            ), mock.patch(
                "r7_runtime.r6_fused_release_precheck.seal_candidate",
                return_value=dict(seal),
            ):
                report = verify_fused_release_precheck(runtime, candidate, seal_path)
            self.assertTrue(report["eligible_for_future_fused_build"])
            self.assertTrue(report["fresh_seal_matches_supplied_seal"])
            self.assertFalse(report["fused_package_created"])
            self.assertFalse(report["readiness_switch_changed"])
            self.assertFalse(report["execution_unlocked"])
            self.assertTrue(report["successor_release_required"])

    def test_baseline_integrity_failure_blocks_precheck(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            seal_path.write_text(json.dumps(self.good_seal()), encoding="utf-8")
            with mock.patch(
                "r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity",
                side_effect=RuntimeError("RUNTIME_HASH_MISMATCH"),
            ):
                with self.assertRaisesRegex(FusedReleasePrecheckError, "BASELINE_PACKAGE_INTEGRITY_FAILED"):
                    verify_fused_release_precheck(runtime, candidate, seal_path)

    def test_baseline_must_still_be_producer_locked(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            seal_path.write_text(json.dumps(self.good_seal()), encoding="utf-8")
            bad = {"causal_r6_producer_ready": True, "execution_runtime_hard_locked": False}
            with mock.patch(
                "r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity",
                return_value=bad,
            ):
                with self.assertRaisesRegex(FusedReleasePrecheckError, "BASELINE_PRODUCER_LOCK_NOT_FALSE"):
                    verify_fused_release_precheck(runtime, candidate, seal_path)

    def test_stale_seal_after_candidate_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            supplied = self.good_seal()
            fresh = self.good_seal()
            fresh["producer_module_sha256"] = "a" * 64
            fresh["candidate_files_sha256"] = dict(fresh["candidate_files_sha256"])
            fresh["candidate_files_sha256"]["r7_runtime/r6_causal_producer.py"] = "a" * 64
            seal_path.write_text(json.dumps(supplied), encoding="utf-8")
            with mock.patch(
                "r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity",
                return_value=self.baseline_integrity(),
            ), mock.patch(
                "r7_runtime.r6_fused_release_precheck.seal_candidate",
                return_value=fresh,
            ):
                with self.assertRaisesRegex(FusedReleasePrecheckError, "STALE_OR_MISMATCHED_SEAL"):
                    verify_fused_release_precheck(runtime, candidate, seal_path)

    def test_seal_claiming_execution_unlock_is_rejected_before_fresh_seal(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            seal = self.good_seal()
            seal["execution_unlocked"] = True
            seal_path.write_text(json.dumps(seal), encoding="utf-8")
            with mock.patch(
                "r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity",
                return_value=self.baseline_integrity(),
            ):
                with self.assertRaisesRegex(FusedReleasePrecheckError, "SEAL_EXECUTION_UNLOCK_CLAIM"):
                    verify_fused_release_precheck(runtime, candidate, seal_path)

    def test_holdout_or_retune_claim_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            seal = self.good_seal()
            seal["final_holdout_accessed"] = True
            seal_path.write_text(json.dumps(seal), encoding="utf-8")
            with mock.patch(
                "r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity",
                return_value=self.baseline_integrity(),
            ):
                with self.assertRaisesRegex(FusedReleasePrecheckError, "SEAL_HOLDOUT_BOUNDARY_BREACH"):
                    verify_fused_release_precheck(runtime, candidate, seal_path)

            seal = self.good_seal()
            seal["strategy_retuned"] = True
            seal_path.write_text(json.dumps(seal), encoding="utf-8")
            with mock.patch(
                "r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity",
                return_value=self.baseline_integrity(),
            ):
                with self.assertRaisesRegex(FusedReleasePrecheckError, "SEAL_RETUNING_BREACH"):
                    verify_fused_release_precheck(runtime, candidate, seal_path)


if __name__ == "__main__":
    unittest.main()
