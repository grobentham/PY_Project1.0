from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from producer_fixture_support import build_trusted_fixture
from r7_runtime.constants import R6_SOURCE_PRIORITY
from r7_runtime.r6_integrity import sha256_file
from r7_runtime.r6_producer_parity import ProducerParityError, build_parity_report


class ProducerParityTests(unittest.TestCase):
    @staticmethod
    def build_report(paths):
        return build_parity_report(
            paths["reference"],
            paths["producer_stream"],
            fixture_path=paths["fixtures"],
            replay_attestation_path=paths["replay"],
            isolation_path=paths["isolation"],
            source_probe_path=paths["probe"],
            source_bundle_manifest_path=paths["bundle"],
            producer_module_path=paths["producer_module"],
            producer_module_relative="r7_runtime/r6_causal_producer.py",
        )

    def test_exact_full_source_coverage_passes_after_trusted_replay(self):
        with tempfile.TemporaryDirectory() as td:
            paths = build_trusted_fixture(Path(td))
            report = self.build_report(paths)
            self.assertTrue(report["trusted_producer_replay_pass"])
            self.assertTrue(report["producer_source_policy_pass"])
            self.assertTrue(report["parity_pass"])
            self.assertEqual(report["mismatch_count"], 0)
            self.assertEqual(report["lookahead_violations"], 0)
            self.assertEqual(set(report["frozen_sources_covered"]), set(R6_SOURCE_PRIORITY))
            self.assertEqual(report["reference_stream_sha256"], sha256_file(paths["reference"]))
            self.assertEqual(report["producer_stream_sha256"], sha256_file(paths["producer_stream"]))
            self.assertEqual(report["fixture_corpus_sha256"], sha256_file(paths["fixtures"]))
            self.assertEqual(report["producer_replay_attestation_sha256"], sha256_file(paths["replay"]))

    def test_missing_source_bundle_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            paths = build_trusted_fixture(Path(td))
            paths["bundle"].unlink()
            with self.assertRaisesRegex(ProducerParityError, "SOURCE_BUNDLE_MANIFEST_MISSING"):
                self.build_report(paths)

    def test_changed_producer_stream_fails_before_parity_comparison(self):
        with tempfile.TemporaryDirectory() as td:
            paths = build_trusted_fixture(Path(td))
            paths["producer_stream"].write_text(paths["producer_stream"].read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ProducerParityError, "PRODUCER_TRUSTED_REPLAY_FAILED"):
                self.build_report(paths)

    def test_selection_mismatch_in_reference_produces_failing_report(self):
        with tempfile.TemporaryDirectory() as td:
            paths = build_trusted_fixture(Path(td))
            rows = [json.loads(x) for x in paths["reference"].read_text(encoding="utf-8").splitlines()]
            rows[0]["decision"]["side"] *= -1
            paths["reference"].write_text("\n".join(json.dumps(x, sort_keys=True) for x in rows) + "\n", encoding="utf-8")
            iso = json.loads(paths["isolation"].read_text(encoding="utf-8"))
            iso["reference_stream_sha256"] = sha256_file(paths["reference"])
            paths["isolation"].write_text(json.dumps(iso), encoding="utf-8")
            report = self.build_report(paths)
            self.assertFalse(report["parity_pass"])
            self.assertEqual(report["mismatch_count"], 1)
            self.assertFalse(report["signal_selection_parity"])

    def test_signal_after_reference_prefix_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            paths = build_trusted_fixture(Path(td))
            rows = [json.loads(x) for x in paths["reference"].read_text(encoding="utf-8").splitlines()]
            rows[0]["available_through_ms"] = rows[0]["decision"]["signal_bar_ms"] - 1
            paths["reference"].write_text("\n".join(json.dumps(x, sort_keys=True) for x in rows) + "\n", encoding="utf-8")
            iso = json.loads(paths["isolation"].read_text(encoding="utf-8"))
            iso["reference_stream_sha256"] = sha256_file(paths["reference"])
            paths["isolation"].write_text(json.dumps(iso), encoding="utf-8")
            report = self.build_report(paths)
            self.assertFalse(report["parity_pass"])
            self.assertGreater(report["lookahead_violations"], 0)

    def test_isolation_future_rows_available_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            paths = build_trusted_fixture(Path(td))
            iso = json.loads(paths["isolation"].read_text(encoding="utf-8"))
            iso["future_rows_available_to_producer"] = True
            paths["isolation"].write_text(json.dumps(iso), encoding="utf-8")
            with self.assertRaisesRegex(ProducerParityError, "PARITY_ISOLATION_GUARD_FAILED"):
                self.build_report(paths)

    def test_isolation_producer_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            paths = build_trusted_fixture(Path(td))
            iso = json.loads(paths["isolation"].read_text(encoding="utf-8"))
            iso["producer_stream_sha256"] = "0" * 64
            paths["isolation"].write_text(json.dumps(iso), encoding="utf-8")
            with self.assertRaisesRegex(ProducerParityError, "PARITY_ISOLATION_PRODUCER_HASH_MISMATCH"):
                self.build_report(paths)

    def test_fixture_set_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            paths = build_trusted_fixture(Path(td))
            rows = paths["reference"].read_text(encoding="utf-8").splitlines()[:-1]
            paths["reference"].write_text("\n".join(rows) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ProducerParityError, "PARITY_FIXTURE_SET_MISMATCH"):
                self.build_report(paths)

    def test_replay_attestation_tamper_fails_before_parity(self):
        with tempfile.TemporaryDirectory() as td:
            paths = build_trusted_fixture(Path(td))
            replay = json.loads(paths["replay"].read_text(encoding="utf-8"))
            replay["deterministic_double_run"] = False
            paths["replay"].write_text(json.dumps(replay), encoding="utf-8")
            with self.assertRaisesRegex(ProducerParityError, "PRODUCER_TRUSTED_REPLAY_FAILED"):
                self.build_report(paths)


if __name__ == "__main__":
    unittest.main()
