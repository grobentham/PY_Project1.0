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
    verify_source_bundle,
)


class ProducerAdmissionTests(unittest.TestCase):
    @staticmethod
    def _rewrite_canonical_source_claim(root: Path, paths, relative: str, text: str) -> None:
        source = root / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(text, encoding="utf-8")
        digest = sha256_file(source)

        parent = json.loads(paths["parent"].read_text(encoding="utf-8"))
        parent["parent_tree_sha256"][relative] = digest
        if relative in parent.get("protected_r6_hashes", {}):
            parent["protected_r6_hashes"][relative] = digest
        paths["parent"].write_text(json.dumps(parent, sort_keys=True), encoding="utf-8")

        bundle = json.loads(paths["bundle"].read_text(encoding="utf-8"))
        if relative in bundle["files"]:
            bundle["files"][relative]["sha256"] = digest
            bundle["files"][relative]["size_bytes"] = source.stat().st_size
        paths["bundle"].write_text(json.dumps(bundle, sort_keys=True), encoding="utf-8")

    @staticmethod
    def _verify_bundle_only(root: Path, paths):
        return verify_source_bundle(
            root,
            parent_manifest_path=paths["parent"],
            source_probe_path=paths["probe"],
            source_bundle_manifest_path=paths["bundle"],
        )

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
            self.assertTrue(result["source_bundle"]["static_dependency_closure_recomputed"])
            self.assertTrue(result["source_bundle"]["dynamic_import_policy_recomputed"])

    def test_claimed_closure_cannot_omit_canonical_local_helper(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = build_trusted_fixture(root)
            helper = root / "v16r5" / "helper.py"
            helper.write_text("VALUE = 7\n", encoding="utf-8")
            parent = json.loads(paths["parent"].read_text(encoding="utf-8"))
            parent["parent_tree_sha256"]["v16r5/helper.py"] = sha256_file(helper)
            paths["parent"].write_text(json.dumps(parent, sort_keys=True), encoding="utf-8")

            original = (root / "v16r5" / "engine.py").read_text(encoding="utf-8")
            self._rewrite_canonical_source_claim(
                root,
                paths,
                "v16r5/engine.py",
                "import v16r5.helper\n" + original,
            )
            with self.assertRaisesRegex(ProducerAdmissionError, "SOURCE_BUNDLE_STATIC_CLOSURE_MISMATCH"):
                self._verify_bundle_only(root, paths)

    def test_manifest_false_claim_cannot_hide_dynamic_import(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = build_trusted_fixture(root)
            original = (root / "v16r5" / "engine.py").read_text(encoding="utf-8")
            self._rewrite_canonical_source_claim(
                root,
                paths,
                "v16r5/engine.py",
                "import importlib\nDYNAMIC_MODULE = importlib.import_module('math')\n" + original,
            )
            with self.assertRaisesRegex(
                ProducerAdmissionError,
                "SOURCE_BUNDLE_STATIC_CLOSURE_RECOMPUTE_FAILED:R6_SOURCE_DYNAMIC_IMPORT_UNRESOLVED",
            ):
                self._verify_bundle_only(root, paths)

    def test_manifest_false_claim_cannot_hide_unresolved_external_import(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = build_trusted_fixture(root)
            original = (root / "V16_R5_MAIN.py").read_text(encoding="utf-8")
            self._rewrite_canonical_source_claim(
                root,
                paths,
                "V16_R5_MAIN.py",
                "import pandas\n" + original,
            )
            with self.assertRaisesRegex(ProducerAdmissionError, "SOURCE_BUNDLE_EXTERNAL_IMPORT_MAP_MISMATCH"):
                self._verify_bundle_only(root, paths)

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
            with self.assertRaisesRegex(
                ProducerAdmissionError,
                "SOURCE_BUNDLE_EXTERNAL_IMPORT_MAP_MISMATCH|PRODUCER_PARITY_SOURCE_BUNDLE_HASH_MISMATCH",
            ):
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
