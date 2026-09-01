from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from r7_runtime.constants import CANONICAL_R6_ZIP_SHA256
from r7_runtime.r6_fused_release_precheck import (
    PRECHECK_VERSION,
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
            "R7_R1_R6_PARITY_FIXTURES.jsonl": "4" * 64,
            "R7_R1_R6_PRODUCER_REPLAY.json": "5" * 64,
            "R7_R1_R6_REFERENCE_STREAM.jsonl": "6" * 64,
            "R7_R1_R6_REFERENCE_REPLAY.json": "a" * 64,
            "R7_R1_R6_PRODUCER_STREAM.jsonl": "7" * 64,
            "R7_R1_R6_PARITY_ISOLATION.json": "8" * 64,
            "R7_R1_R6_PRODUCER_PARITY.json": "9" * 64,
        }
        return {
            "seal_version": SEAL_VERSION,
            "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
            "candidate_files_sha256": hashes,
            "producer_module": "r7_runtime/r6_causal_producer.py",
            "producer_module_sha256": hashes["r7_runtime/r6_causal_producer.py"],
            "fixture_corpus_sha256": hashes["R7_R1_R6_PARITY_FIXTURES.jsonl"],
            "producer_replay_attestation_sha256": hashes["R7_R1_R6_PRODUCER_REPLAY.json"],
            "reference_stream_sha256": hashes["R7_R1_R6_REFERENCE_STREAM.jsonl"],
            "reference_replay_attestation_sha256": hashes["R7_R1_R6_REFERENCE_REPLAY.json"],
            "producer_stream_sha256": hashes["R7_R1_R6_PRODUCER_STREAM.jsonl"],
            "admission_version": "TEST_ADMISSION_V4",
            "authority_version": "TEST_AUTHORITY_V5",
            "admission_ready": True,
            "canonical_reference_replay_pass": True,
            "trusted_producer_replay_pass": True,
            "producer_source_policy_pass": True,
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
            self.assertEqual(report["precheck_version"], PRECHECK_VERSION)
            self.assertTrue(report["eligible_for_future_fused_build"])
            self.assertTrue(report["fresh_seal_matches_supplied_seal"])
            self.assertTrue(report["canonical_reference_replay_pass"])
            self.assertEqual(report["authority_version"], "TEST_AUTHORITY_V5")
            self.assertTrue(report["trusted_producer_replay_pass"])
            self.assertTrue(report["producer_source_policy_pass"])
            self.assertEqual(report["fixture_corpus_sha256"], seal["fixture_corpus_sha256"])
            self.assertEqual(report["reference_stream_sha256"], seal["reference_stream_sha256"])
            self.assertEqual(report["reference_replay_attestation_sha256"], seal["reference_replay_attestation_sha256"])
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

    def test_stale_seal_after_reference_replay_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            supplied = self.good_seal()
            fresh = self.good_seal()
            fresh["reference_replay_attestation_sha256"] = "b" * 64
            fresh["candidate_files_sha256"] = dict(fresh["candidate_files_sha256"])
            fresh["candidate_files_sha256"]["R7_R1_R6_REFERENCE_REPLAY.json"] = "b" * 64
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

    def test_reference_replay_claim_cannot_be_downgraded(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            seal = self.good_seal()
            seal["canonical_reference_replay_pass"] = False
            seal_path.write_text(json.dumps(seal), encoding="utf-8")
            with mock.patch(
                "r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity",
                return_value=self.baseline_integrity(),
            ):
                with self.assertRaisesRegex(FusedReleasePrecheckError, "SEAL_CANONICAL_REFERENCE_REPLAY_NOT_PASS"):
                    verify_fused_release_precheck(runtime, candidate, seal_path)

    def test_missing_authority_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            seal = self.good_seal()
            seal["authority_version"] = ""
            seal_path.write_text(json.dumps(seal), encoding="utf-8")
            with mock.patch(
                "r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity",
                return_value=self.baseline_integrity(),
            ):
                with self.assertRaisesRegex(FusedReleasePrecheckError, "SEAL_AUTHORITY_VERSION_MISSING"):
                    verify_fused_release_precheck(runtime, candidate, seal_path)

    def test_replay_or_source_policy_claim_cannot_be_downgraded(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            for field, error in (
                ("trusted_producer_replay_pass", "SEAL_TRUSTED_REPLAY_NOT_PASS"),
                ("producer_source_policy_pass", "SEAL_SOURCE_POLICY_NOT_PASS"),
            ):
                seal = self.good_seal()
                seal[field] = False
                seal_path.write_text(json.dumps(seal), encoding="utf-8")
                with mock.patch(
                    "r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity",
                    return_value=self.baseline_integrity(),
                ):
                    with self.assertRaisesRegex(FusedReleasePrecheckError, error):
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
