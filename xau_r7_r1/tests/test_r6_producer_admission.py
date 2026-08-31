from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from r7_runtime.constants import (
    CANONICAL_R6_ZIP_SHA256,
    RETIRED_SOURCE,
    R6_DECISION_POLICY,
    R6_DECISION_SCHEMA,
    R6_SOURCE_PRIORITY,
)
from r7_runtime.r6_integrity import sha256_file
from r7_runtime.r6_producer_admission import (
    REQUIRED_FROZEN_SOURCES,
    ProducerAdmissionError,
    producer_admission_status,
    verify_producer_admission,
)
from r7_runtime.r6_producer_parity import ISOLATION_SCHEMA, build_parity_report
from r7_runtime.r6_source_bundle import BUNDLE_VERSION
from r7_runtime.r6_source_probe import probe_frozen_r6_source


class ProducerAdmissionTests(unittest.TestCase):
    @staticmethod
    def decision(source: str, i: int):
        signal = 1_700_000_000_000 + i * 60_000
        return {
            "schema": R6_DECISION_SCHEMA,
            "policy": R6_DECISION_POLICY,
            "parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
            "decision_id": "admission_fixture_" + str(i),
            "signal_bar_ms": signal,
            "emitted_at_ms": signal + 1000,
            "side": 1 if i % 2 == 0 else -1,
            "source": source,
            "priority": R6_SOURCE_PRIORITY[source],
            "family": "BASE" if source == "CORE" else "FAMILY_" + source,
            "signal_type": "BASE_SIGNAL" if source == "CORE" else "SIGNAL_" + source,
            "atr_usd": 2.0 + i / 10.0,
            "stop_atr": 1.0,
            "target_atr": 2.0,
            "geometry_used": "PRIMARY",
            "lot_size": 0.01,
            "admitted": True,
        }

    def build_fixture(self, root: Path):
        sources = {
            "v16r6/engine.py": (
                'RETIRED_SOURCE = "AUX_RF_LTM"\n'
                'def build_r6_universe(root):\n    return root\n\n'
                'def build_r6(root, **kwargs):\n    return root, kwargs\n'
            ),
            "v16r5/engine.py": (
                'def build_r5_universe(root):\n    return root\n\n'
                'def simulate_r5(universe, **kwargs):\n    return universe\n\n'
                'def summary(value):\n    return value\n\n'
                'def component_audit(value):\n    return value\n'
            ),
            "V16_R5_MAIN.py": 'FROZEN = True\n',
        }
        for relative, text in sources.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

        source_hashes = {relative: sha256_file(root / relative) for relative in sources}
        parent = {
            "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
            "build_verified_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
            "protected_r6_hashes": dict(source_hashes),
            "parent_tree_sha256": dict(source_hashes),
        }
        parent_path = root / "R7_R1_PARENT_INTEGRITY.json"
        parent_path.write_text(json.dumps(parent), encoding="utf-8")

        probe_path = root / "R7_R1_R6_SOURCE_PROBE.json"
        probe_path.write_text(json.dumps(probe_frozen_r6_source(root), sort_keys=True), encoding="utf-8")

        bundle_path = root / "R7_R1_R6_SOURCE_BUNDLE_MANIFEST.json"
        bundle_path.write_text(json.dumps({
            "bundle_version": BUNDLE_VERSION,
            "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
            "source_only_bundle": True,
            "static_local_python_dependency_closure_extracted": True,
            "required_local_imports_resolved": True,
            "dynamic_imports_allowed": False,
            "dependency_count": len(sources),
            "required_source_files": list(sources),
            "dependency_closure_files": list(sources),
            "unresolved_nonarchive_imports": {},
            "strategy_executed": False,
            "strategy_retuned": False,
            "final_holdout_accessed": False,
            "producer_admitted": False,
            "files": {
                relative: {
                    "sha256": source_hashes[relative],
                    "size_bytes": (root / relative).stat().st_size,
                    "required_entry_source": True,
                }
                for relative in sources
            },
            "source_probe_file": probe_path.name,
            "source_probe_sha256": sha256_file(probe_path),
        }, sort_keys=True), encoding="utf-8")

        producer_module = root / "r7_runtime" / "r6_causal_producer.py"
        producer_module.parent.mkdir(parents=True, exist_ok=True)
        producer_module.write_text('def produce(prefix):\n    return prefix\n', encoding="utf-8")

        reference_rows, producer_rows = [], []
        for i, source in enumerate(sorted(REQUIRED_FROZEN_SOURCES, key=R6_SOURCE_PRIORITY.get)):
            decision = self.decision(source, i)
            cutoff = decision["signal_bar_ms"]
            reference_rows.append({"fixture_id": "fx_" + str(i), "available_through_ms": cutoff, "decision": decision})
            producer_rows.append({"fixture_id": "fx_" + str(i), "available_through_ms": cutoff, "decision": dict(decision)})

        reference_path = root / "R7_R1_R6_REFERENCE_STREAM.jsonl"
        producer_stream_path = root / "R7_R1_R6_PRODUCER_STREAM.jsonl"
        reference_path.write_text("\n".join(json.dumps(x, sort_keys=True) for x in reference_rows) + "\n", encoding="utf-8")
        producer_stream_path.write_text("\n".join(json.dumps(x, sort_keys=True) for x in producer_rows) + "\n", encoding="utf-8")

        isolation_path = root / "R7_R1_R6_PARITY_ISOLATION.json"
        isolation_path.write_text(json.dumps({
            "schema": ISOLATION_SCHEMA,
            "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
            "reference_stream_sha256": sha256_file(reference_path),
            "producer_stream_sha256": sha256_file(producer_stream_path),
            "fixture_count": len(reference_rows),
            "causal_prefix_fixture_generation": True,
            "future_rows_available_to_producer": False,
            "outcome_columns_present": False,
            "final_holdout_accessed": False,
            "strategy_retuned": False,
        }), encoding="utf-8")

        parity = build_parity_report(
            reference_path,
            producer_stream_path,
            isolation_path=isolation_path,
            source_probe_path=probe_path,
            source_bundle_manifest_path=bundle_path,
            producer_module_path=producer_module,
            producer_module_relative="r7_runtime/r6_causal_producer.py",
        )
        parity_path = root / "R7_R1_R6_PRODUCER_PARITY.json"
        parity_path.write_text(json.dumps(parity), encoding="utf-8")
        return {
            "parent": parent_path,
            "probe": probe_path,
            "bundle": bundle_path,
            "producer_module": producer_module,
            "reference": reference_path,
            "producer_stream": producer_stream_path,
            "isolation": isolation_path,
            "parity": parity_path,
        }

    def test_complete_machine_derived_evidence_can_pass_admission_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.build_fixture(root)
            result = verify_producer_admission(root)
            self.assertTrue(result["ready"])
            self.assertTrue(result["parity"]["parity_pass"])
            self.assertEqual(set(result["parity"]["frozen_sources_covered"]), set(REQUIRED_FROZEN_SOURCES))
            self.assertEqual(result["source_bundle"]["dependency_count"], 3)

    def test_source_bytes_changed_after_probe_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.build_fixture(root)
            (root / "v16r5" / "engine.py").write_text("tampered = True\n", encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "SOURCE_BUNDLE_FILE_SIZE_MISMATCH|SOURCE_BUNDLE_FILE_HASH_MISMATCH"):
                verify_producer_admission(root)

    def test_bundle_helper_hash_must_match_canonical_parent_tree(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self.build_fixture(root)
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
            paths = self.build_fixture(root)
            bundle = json.loads(paths["bundle"].read_text(encoding="utf-8"))
            bundle["unresolved_nonarchive_imports"] = {"v16r5/engine.py": ["import pandas"]}
            paths["bundle"].write_text(json.dumps(bundle), encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "PRODUCER_PARITY_SOURCE_BUNDLE_HASH_MISMATCH"):
                verify_producer_admission(root)

    def test_prohibited_holdout_path_in_bundle_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self.build_fixture(root)
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

    def test_any_parity_mismatch_claim_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self.build_fixture(root)
            parity = json.loads(paths["parity"].read_text(encoding="utf-8"))
            parity["mismatch_count"] = 1
            paths["parity"].write_text(json.dumps(parity), encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "PRODUCER_PARITY_MISMATCHES_PRESENT"):
                verify_producer_admission(root)

    def test_future_row_read_claim_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self.build_fixture(root)
            parity = json.loads(paths["parity"].read_text(encoding="utf-8"))
            parity["future_rows_read"] = True
            paths["parity"].write_text(json.dumps(parity), encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "PRODUCER_PARITY_FUTURE_ROW_READ"):
                verify_producer_admission(root)

    def test_retired_source_cannot_be_marked_covered(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self.build_fixture(root)
            parity = json.loads(paths["parity"].read_text(encoding="utf-8"))
            parity["frozen_sources_covered"].append(RETIRED_SOURCE)
            paths["parity"].write_text(json.dumps(parity), encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "PRODUCER_PARITY_RETIRED_SOURCE_MARKED_COVERED"):
                verify_producer_admission(root)

    def test_producer_code_hash_mismatch_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self.build_fixture(root)
            paths["producer_module"].write_text('def produce(prefix):\n    return None\n', encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "PRODUCER_MODULE_HASH_MISMATCH"):
                verify_producer_admission(root)

    def test_detached_or_changed_producer_stream_fails_hash_binding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self.build_fixture(root)
            paths["producer_stream"].write_text(paths["producer_stream"].read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "PRODUCER_PARITY_PRODUCER_STREAM_HASH_MISMATCH"):
                verify_producer_admission(root)

    def test_isolation_manifest_tamper_fails_hash_binding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self.build_fixture(root)
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
