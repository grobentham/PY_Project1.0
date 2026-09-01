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
from r7_runtime.r6_producer_seal import SEAL_VERSION
from r7_runtime.r6_source_bundle import BUNDLE_VERSION


class FusedReleasePrecheckTests(unittest.TestCase):
    def build_paths(self, root: Path):
        runtime = root / "runtime"
        candidate = root / "candidate"
        runtime.mkdir(); candidate.mkdir()
        return runtime, candidate, candidate / "R7_R1_R6_PRODUCER_CANDIDATE_SEAL.json"

    @staticmethod
    def security_contract():
        return {
            "replay_version": REPLAY_VERSION,
            "source_policy_version": SOURCE_POLICY_VERSION,
            "process_isolation_enforced": True,
            "worker_module_sha256": "f" * 64,
            "wall_timeout_seconds": MAX_REPLAY_WALL_SECONDS,
            "max_fixture_count": MAX_FIXTURE_COUNT,
            "max_input_depth": MAX_INPUT_DEPTH,
            "max_input_nodes_per_fixture": MAX_INPUT_NODES_PER_FIXTURE,
            "max_range_items": MAX_RANGE_ITEMS,
            "max_execution_line_events": MAX_EXECUTION_LINE_EVENTS,
        }

    @staticmethod
    def source_bundle_contract():
        return {
            "bundle_version": BUNDLE_VERSION,
            "static_dependency_closure_recomputed": True,
            "dynamic_import_policy_recomputed": True,
            "prohibited_source_paths_blocked": True,
            "owned_output_replacement_only": True,
            "ownership_marker_sha256": "d" * 64,
        }

    @staticmethod
    def reference_source_contract():
        return {
            "source_bundle_version": BUNDLE_VERSION,
            "source_bundle_static_closure_recomputed": True,
            "source_bundle_dynamic_import_policy_recomputed": True,
            "source_bundle_prohibited_paths_blocked": True,
            "reference_generated_by_exact_canonical_source_executor": True,
        }

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
            "reference_source_security_contract_pass": True,
            "reference_source_security_contract": self.reference_source_contract(),
            "source_bundle_security_contract_pass": True,
            "source_bundle_security_contract": self.source_bundle_contract(),
            "trusted_replay_security_contract_pass": True,
            "trusted_replay_security_contract": self.security_contract(),
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
        return {"causal_r6_producer_ready": False, "execution_runtime_hard_locked": True}

    def run_with_good_baseline(self, runtime, candidate, seal_path, fresh=None):
        supplied = self.good_seal()
        seal_path.write_text(json.dumps(supplied), encoding="utf-8")
        with mock.patch(
            "r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity",
            return_value=self.baseline_integrity(),
        ), mock.patch(
            "r7_runtime.r6_fused_release_precheck.seal_candidate",
            return_value=dict(supplied if fresh is None else fresh),
        ):
            return verify_fused_release_precheck(runtime, candidate, seal_path)

    def test_matching_fresh_v4_seal_only_grants_future_fused_build_eligibility(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            report = self.run_with_good_baseline(runtime, candidate, seal_path)
            self.assertEqual(report["precheck_version"], PRECHECK_VERSION)
            self.assertTrue(report["eligible_for_future_fused_build"])
            self.assertTrue(report["fresh_seal_matches_supplied_seal"])
            self.assertTrue(report["reference_source_security_contract_pass"])
            self.assertEqual(report["reference_source_security_contract"], self.reference_source_contract())
            self.assertTrue(report["source_bundle_security_contract_pass"])
            self.assertEqual(report["source_bundle_security_contract"], self.source_bundle_contract())
            self.assertTrue(report["trusted_replay_security_contract_pass"])
            self.assertEqual(report["trusted_replay_security_contract"], self.security_contract())
            self.assertTrue(report["canonical_reference_replay_pass"])
            self.assertEqual(report["authority_version"], "TEST_AUTHORITY_V5")
            self.assertTrue(report["trusted_producer_replay_pass"])
            self.assertTrue(report["producer_source_policy_pass"])
            self.assertFalse(report["fused_package_created"])
            self.assertFalse(report["readiness_switch_changed"])
            self.assertFalse(report["execution_unlocked"])
            self.assertTrue(report["successor_release_required"])

    def test_old_v3_seal_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            seal = self.good_seal(); seal["seal_version"] = "R7_R1_R6_PRODUCER_CANDIDATE_SEAL_V3"
            seal_path.write_text(json.dumps(seal), encoding="utf-8")
            with mock.patch("r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity", return_value=self.baseline_integrity()):
                with self.assertRaisesRegex(FusedReleasePrecheckError, "SEAL_VERSION_MISMATCH"):
                    verify_fused_release_precheck(runtime, candidate, seal_path)

    def test_v4_seal_missing_source_provenance_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            for field, error in (
                ("source_bundle_security_contract_pass", "SEAL_SOURCE_BUNDLE_SECURITY_CONTRACT_NOT_PASS"),
                ("reference_source_security_contract_pass", "SEAL_REFERENCE_SOURCE_SECURITY_CONTRACT_NOT_PASS"),
            ):
                seal = self.good_seal(); seal[field] = False
                seal_path.write_text(json.dumps(seal), encoding="utf-8")
                with mock.patch("r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity", return_value=self.baseline_integrity()):
                    with self.assertRaisesRegex(FusedReleasePrecheckError, error):
                        verify_fused_release_precheck(runtime, candidate, seal_path)

    def test_source_closure_guard_cannot_be_downgraded(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            seal = self.good_seal()
            seal["source_bundle_security_contract"] = dict(seal["source_bundle_security_contract"])
            seal["source_bundle_security_contract"]["static_dependency_closure_recomputed"] = False
            seal_path.write_text(json.dumps(seal), encoding="utf-8")
            with mock.patch("r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity", return_value=self.baseline_integrity()):
                with self.assertRaisesRegex(FusedReleasePrecheckError, "SEAL_SOURCE_BUNDLE_GUARD_NOT_PASS:static_dependency_closure_recomputed"):
                    verify_fused_release_precheck(runtime, candidate, seal_path)

    def test_baseline_integrity_failure_blocks_precheck(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            seal_path.write_text(json.dumps(self.good_seal()), encoding="utf-8")
            with mock.patch("r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity", side_effect=RuntimeError("RUNTIME_HASH_MISMATCH")):
                with self.assertRaisesRegex(FusedReleasePrecheckError, "BASELINE_PACKAGE_INTEGRITY_FAILED"):
                    verify_fused_release_precheck(runtime, candidate, seal_path)

    def test_baseline_must_still_be_producer_locked(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            seal_path.write_text(json.dumps(self.good_seal()), encoding="utf-8")
            bad = {"causal_r6_producer_ready": True, "execution_runtime_hard_locked": False}
            with mock.patch("r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity", return_value=bad):
                with self.assertRaisesRegex(FusedReleasePrecheckError, "BASELINE_PRODUCER_LOCK_NOT_FALSE"):
                    verify_fused_release_precheck(runtime, candidate, seal_path)

    def test_replay_security_contract_claim_cannot_be_downgraded(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            for mutate, error in (
                (lambda s: s.__setitem__("trusted_replay_security_contract_pass", False), "SEAL_REPLAY_SECURITY_CONTRACT_NOT_PASS"),
                (lambda s: s["trusted_replay_security_contract"].__setitem__("process_isolation_enforced", False), "SEAL_REPLAY_PROCESS_ISOLATION_NOT_PASS"),
            ):
                seal = self.good_seal(); mutate(seal)
                seal_path.write_text(json.dumps(seal), encoding="utf-8")
                with mock.patch("r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity", return_value=self.baseline_integrity()):
                    with self.assertRaisesRegex(FusedReleasePrecheckError, error):
                        verify_fused_release_precheck(runtime, candidate, seal_path)

    def test_stale_seal_after_reference_replay_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            supplied = self.good_seal(); fresh = self.good_seal()
            fresh["reference_replay_attestation_sha256"] = "b" * 64
            fresh["candidate_files_sha256"] = dict(fresh["candidate_files_sha256"])
            fresh["candidate_files_sha256"]["R7_R1_R6_REFERENCE_REPLAY.json"] = "b" * 64
            seal_path.write_text(json.dumps(supplied), encoding="utf-8")
            with mock.patch("r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity", return_value=self.baseline_integrity()), mock.patch("r7_runtime.r6_fused_release_precheck.seal_candidate", return_value=fresh):
                with self.assertRaisesRegex(FusedReleasePrecheckError, "STALE_OR_MISMATCHED_SEAL"):
                    verify_fused_release_precheck(runtime, candidate, seal_path)

    def test_stale_seal_after_source_security_contract_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            supplied = self.good_seal(); fresh = self.good_seal()
            fresh["source_bundle_security_contract"] = dict(fresh["source_bundle_security_contract"])
            fresh["source_bundle_security_contract"]["ownership_marker_sha256"] = "c" * 64
            seal_path.write_text(json.dumps(supplied), encoding="utf-8")
            with mock.patch("r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity", return_value=self.baseline_integrity()), mock.patch("r7_runtime.r6_fused_release_precheck.seal_candidate", return_value=fresh):
                with self.assertRaisesRegex(FusedReleasePrecheckError, "STALE_OR_MISMATCHED_SEAL:source_bundle_security_contract"):
                    verify_fused_release_precheck(runtime, candidate, seal_path)

    def test_stale_seal_after_replay_security_contract_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            supplied = self.good_seal(); fresh = self.good_seal()
            fresh["trusted_replay_security_contract"] = dict(fresh["trusted_replay_security_contract"])
            fresh["trusted_replay_security_contract"]["worker_module_sha256"] = "e" * 64
            seal_path.write_text(json.dumps(supplied), encoding="utf-8")
            with mock.patch("r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity", return_value=self.baseline_integrity()), mock.patch("r7_runtime.r6_fused_release_precheck.seal_candidate", return_value=fresh):
                with self.assertRaisesRegex(FusedReleasePrecheckError, "STALE_OR_MISMATCHED_SEAL:trusted_replay_security_contract"):
                    verify_fused_release_precheck(runtime, candidate, seal_path)

    def test_seal_claiming_execution_unlock_is_rejected_before_fresh_seal(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            seal = self.good_seal(); seal["execution_unlocked"] = True
            seal_path.write_text(json.dumps(seal), encoding="utf-8")
            with mock.patch("r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity", return_value=self.baseline_integrity()):
                with self.assertRaisesRegex(FusedReleasePrecheckError, "SEAL_EXECUTION_UNLOCK_CLAIM"):
                    verify_fused_release_precheck(runtime, candidate, seal_path)

    def test_reference_replay_claim_cannot_be_downgraded(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            seal = self.good_seal(); seal["canonical_reference_replay_pass"] = False
            seal_path.write_text(json.dumps(seal), encoding="utf-8")
            with mock.patch("r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity", return_value=self.baseline_integrity()):
                with self.assertRaisesRegex(FusedReleasePrecheckError, "SEAL_CANONICAL_REFERENCE_REPLAY_NOT_PASS"):
                    verify_fused_release_precheck(runtime, candidate, seal_path)

    def test_missing_authority_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            seal = self.good_seal(); seal["authority_version"] = ""
            seal_path.write_text(json.dumps(seal), encoding="utf-8")
            with mock.patch("r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity", return_value=self.baseline_integrity()):
                with self.assertRaisesRegex(FusedReleasePrecheckError, "SEAL_AUTHORITY_VERSION_MISSING"):
                    verify_fused_release_precheck(runtime, candidate, seal_path)

    def test_replay_or_source_policy_claim_cannot_be_downgraded(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            for field, error in (("trusted_producer_replay_pass", "SEAL_TRUSTED_REPLAY_NOT_PASS"), ("producer_source_policy_pass", "SEAL_SOURCE_POLICY_NOT_PASS")):
                seal = self.good_seal(); seal[field] = False
                seal_path.write_text(json.dumps(seal), encoding="utf-8")
                with mock.patch("r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity", return_value=self.baseline_integrity()):
                    with self.assertRaisesRegex(FusedReleasePrecheckError, error):
                        verify_fused_release_precheck(runtime, candidate, seal_path)

    def test_holdout_or_retune_claim_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            runtime, candidate, seal_path = self.build_paths(Path(td))
            for field, error in (("final_holdout_accessed", "SEAL_HOLDOUT_BOUNDARY_BREACH"), ("strategy_retuned", "SEAL_RETUNING_BREACH")):
                seal = self.good_seal(); seal[field] = True
                seal_path.write_text(json.dumps(seal), encoding="utf-8")
                with mock.patch("r7_runtime.r6_fused_release_precheck.verify_runtime_package_integrity", return_value=self.baseline_integrity()):
                    with self.assertRaisesRegex(FusedReleasePrecheckError, error):
                        verify_fused_release_precheck(runtime, candidate, seal_path)


if __name__ == "__main__":
    unittest.main()
