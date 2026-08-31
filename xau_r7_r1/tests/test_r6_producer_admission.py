from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from producer_fixture_support import build_trusted_fixture
from r7_runtime.constants import RETIRED_SOURCE
from r7_runtime.r6_integrity import sha256_file
from r7_runtime.r6_producer_admission import (
    REQUIRED_FROZEN_SOURCES,
    ProducerAdmissionError,
    producer_admission_status,
    verify_producer_admission,
)


class ProducerAdmissionTests(unittest.TestCase):
    def test_trusted_replay_evidence_can_pass_admission_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_trusted_fixture(root)
            result = verify_producer_admission(root)
            self.assertTrue(result["ready"])
            self.assertTrue(result["trusted_replay"]["deterministic_double_run"])
            self.assertTrue(result["parity"]["trusted_producer_replay_pass"])
            self.assertTrue(result["parity"]["producer_source_policy_pass"])
            self.assertTrue(result["parity"]["parity_pass"])
            self.assertEqual(set(result["parity"]["frozen_sources_covered"]), set(REQUIRED_FROZEN_SOURCES))
            self.assertEqual(result["source_bundle"]["dependency_count"], 3)

    def test_source_bytes_changed_after_probe_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_trusted_fixture(root)
            (root / "v16r5" / "engine.py").write_text("tampered = True\n", encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "SOURCE_BUNDLE_FILE_SIZE_MISMATCH|SOURCE_BUNDLE_FILE_HASH_MISMATCH"):
                verify_producer_admission(root)

    def test_bundle_helper_hash_must_match_canonical_parent_tree(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = build_trusted_fixture(root)
            bundle = json.loads(paths["bundle"].read_text(encoding="utf-8"))
            bundle["files"]["v16r5/engine.py"]["sha256"] = "0" * 64
            paths["bundle"].write_text(json.dumps(bundle), encoding="utf-8")
            parity = json.loads(paths["parity"].read_text(encoding="utf-8"))
            parity["source_bundle_manifest_sha256"] = sha256_file(paths["bundle"])
            paths["parity"].write_text(json.dumps(parity), encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "SOURCE_BUNDLE_FILE_HASH_MISMATCH|SOURCE_BUNDLE_NOT_CANONICAL_PARENT_BYTES"):
                verify_producer_admission(root)

    def test_bundle_manifest_tamper_invalidates_parity_binding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = build_trusted_fixture(root)
            bundle = json.loads(paths["bundle"].read_text(encoding="utf-8"))
            bundle["unresolved_nonarchive_imports"] = {"v16r5/engine.py": ["import pandas"]}
            paths["bundle"].write_text(json.dumps(bundle), encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "PRODUCER_PARITY_SOURCE_BUNDLE_HASH_MISMATCH"):
                verify_producer_admission(root)

    def test_prohibited_holdout_path_in_bundle_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = build_trusted_fixture(root)
            extra = root / "final_holdout_helper.py"
            extra.write_text("VALUE=1\n", encoding="utf-8")
            parent = json.loads(paths["parent"].read_text(encoding="utf-8"))
            parent["parent_tree_sha256"]["final_holdout_helper.py"] = sha256_file(extra)
            paths["parent"].write_text(json.dumps(parent), encoding="utf-8")
            bundle = json.loads(paths["bundle"].read_text(encoding="utf-8"))
            bundle["dependency_count"] += 1
            bundle["dependency_closure_files"].append("final_holdout_helper.py")
            bundle["files"]["final_holdout_helper.py"] = {
                "sha256": sha256_file(extra), "size_bytes": extra.stat().st_size, "required_entry_source": False
            }
            paths["bundle"].write_text(json.dumps(bundle), encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "SOURCE_BUNDLE_PROHIBITED_PATH"):
                verify_producer_admission(root)

    def test_parity_mismatch_claim_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = build_trusted_fixture(root)
            parity = json.loads(paths["parity"].read_text(encoding="utf-8"))
            parity["mismatch_count"] = 1
            paths["parity"].write_text(json.dumps(parity), encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "PRODUCER_PARITY_MISMATCHES_PRESENT"):
                verify_producer_admission(root)

    def test_future_row_read_claim_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = build_trusted_fixture(root)
            parity = json.loads(paths["parity"].read_text(encoding="utf-8"))
            parity["future_rows_read"] = True
            paths["parity"].write_text(json.dumps(parity), encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "PRODUCER_PARITY_FUTURE_ROW_READ"):
                verify_producer_admission(root)

    def test_retired_source_cannot_be_marked_covered(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = build_trusted_fixture(root)
            parity = json.loads(paths["parity"].read_text(encoding="utf-8"))
            parity["frozen_sources_covered"].append(RETIRED_SOURCE)
            paths["parity"].write_text(json.dumps(parity), encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "PRODUCER_PARITY_RETIRED_SOURCE_MARKED_COVERED"):
                verify_producer_admission(root)

    def test_changed_producer_code_fails_trusted_replay(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = build_trusted_fixture(root)
            paths["producer_module"].write_text('def produce(prefix):\n    return None\n', encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "PRODUCER_TRUSTED_REPLAY_FAILED"):
                verify_producer_admission(root)

    def test_detached_or_changed_producer_stream_fails_trusted_replay(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = build_trusted_fixture(root)
            paths["producer_stream"].write_text(paths["producer_stream"].read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "PRODUCER_TRUSTED_REPLAY_FAILED"):
                verify_producer_admission(root)

    def test_replay_attestation_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = build_trusted_fixture(root)
            replay = json.loads(paths["replay"].read_text(encoding="utf-8"))
            replay["deterministic_double_run"] = False
            paths["replay"].write_text(json.dumps(replay), encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "PRODUCER_TRUSTED_REPLAY_FAILED"):
                verify_producer_admission(root)

    def test_fixture_corpus_tamper_fails_replay_or_hash_binding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = build_trusted_fixture(root)
            rows = paths["fixtures"].read_text(encoding="utf-8").splitlines()
            row = json.loads(rows[0])
            row["producer_input"]["decision"]["side"] *= -1
            rows[0] = json.dumps(row, sort_keys=True)
            paths["fixtures"].write_text("\n".join(rows) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "PRODUCER_TRUSTED_REPLAY_FAILED|PRODUCER_PARITY_FIXTURE_HASH_MISMATCH"):
                verify_producer_admission(root)

    def test_isolation_manifest_tamper_fails_hash_binding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = build_trusted_fixture(root)
            isolation = json.loads(paths["isolation"].read_text(encoding="utf-8"))
            isolation["future_rows_available_to_producer"] = True
            paths["isolation"].write_text(json.dumps(isolation), encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "PRODUCER_PARITY_ISOLATION_HASH_MISMATCH"):
                verify_producer_admission(root)

    def test_missing_real_evidence_reports_not_ready(self):
        with tempfile.TemporaryDirectory() as td:
            status = producer_admission_status(Path(td))
            self.assertFalse(status["ready"])
            self.assertIn("UNREADABLE", status["reason"])


if __name__ == "__main__":
    unittest.main()
