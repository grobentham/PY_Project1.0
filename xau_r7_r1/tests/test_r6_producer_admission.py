from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from r7_runtime.constants import CANONICAL_R6_ZIP_SHA256, RETIRED_SOURCE
from r7_runtime.r6_integrity import sha256_file
from r7_runtime.r6_producer_admission import (
    PARITY_SCHEMA,
    REQUIRED_FROZEN_SOURCES,
    ProducerAdmissionError,
    producer_admission_status,
    verify_producer_admission,
)
from r7_runtime.r6_source_probe import probe_frozen_r6_source


class ProducerAdmissionTests(unittest.TestCase):
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

        protected = {relative: sha256_file(root / relative) for relative in sources}
        parent = {
            "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
            "build_verified_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
            "protected_r6_hashes": protected,
        }
        parent_path = root / "R7_R1_PARENT_INTEGRITY.json"
        parent_path.write_text(json.dumps(parent), encoding="utf-8")

        probe_path = root / "R7_R1_R6_SOURCE_PROBE.json"
        probe_path.write_text(json.dumps(probe_frozen_r6_source(root), sort_keys=True), encoding="utf-8")

        producer = root / "r7_runtime" / "r6_causal_producer.py"
        producer.parent.mkdir(parents=True, exist_ok=True)
        producer.write_text('def produce(prefix):\n    return prefix\n', encoding="utf-8")

        parity = {
            "schema": PARITY_SCHEMA,
            "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
            "source_probe_sha256": sha256_file(probe_path),
            "producer_module": "r7_runtime/r6_causal_producer.py",
            "producer_module_sha256": sha256_file(producer),
            "parity_pass": True,
            "causal_prefix_only": True,
            "signal_selection_parity": True,
            "source_priority_parity": True,
            "geometry_parity": True,
            "lot_parity": True,
            "timestamp_causality_parity": True,
            "future_rows_read": False,
            "outcome_columns_read": False,
            "final_holdout_accessed": False,
            "strategy_retuned": False,
            "fixture_count": 25,
            "compared_decisions": 25,
            "mismatch_count": 0,
            "lookahead_violations": 0,
            "retired_source_emissions": 0,
            "frozen_sources_covered": sorted(REQUIRED_FROZEN_SOURCES),
        }
        parity_path = root / "R7_R1_R6_PRODUCER_PARITY.json"
        parity_path.write_text(json.dumps(parity), encoding="utf-8")
        return parent_path, probe_path, producer, parity_path

    def test_complete_exact_evidence_can_pass_admission_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.build_fixture(root)
            result = verify_producer_admission(root)
            self.assertTrue(result["ready"])
            self.assertTrue(result["parity"]["parity_pass"])
            self.assertEqual(set(result["parity"]["frozen_sources_covered"]), set(REQUIRED_FROZEN_SOURCES))

    def test_source_bytes_changed_after_probe_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.build_fixture(root)
            (root / "v16r5" / "engine.py").write_text("tampered = True\n", encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "SOURCE_FILE_HASH_MISMATCH"):
                verify_producer_admission(root)

    def test_any_parity_mismatch_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, _, _, parity_path = self.build_fixture(root)
            parity = json.loads(parity_path.read_text(encoding="utf-8"))
            parity["mismatch_count"] = 1
            parity_path.write_text(json.dumps(parity), encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "PRODUCER_PARITY_MISMATCHES_PRESENT"):
                verify_producer_admission(root)

    def test_future_row_read_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, _, _, parity_path = self.build_fixture(root)
            parity = json.loads(parity_path.read_text(encoding="utf-8"))
            parity["future_rows_read"] = True
            parity_path.write_text(json.dumps(parity), encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "PRODUCER_PARITY_FUTURE_ROW_READ"):
                verify_producer_admission(root)

    def test_retired_source_cannot_be_covered_or_emitted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, _, _, parity_path = self.build_fixture(root)
            parity = json.loads(parity_path.read_text(encoding="utf-8"))
            parity["frozen_sources_covered"].append(RETIRED_SOURCE)
            parity_path.write_text(json.dumps(parity), encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "PRODUCER_PARITY_RETIRED_SOURCE_MARKED_COVERED"):
                verify_producer_admission(root)

    def test_producer_code_hash_mismatch_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, _, producer, _ = self.build_fixture(root)
            producer.write_text('def produce(prefix):\n    return None\n', encoding="utf-8")
            with self.assertRaisesRegex(ProducerAdmissionError, "PRODUCER_MODULE_HASH_MISMATCH"):
                verify_producer_admission(root)

    def test_missing_real_evidence_reports_not_ready(self):
        with tempfile.TemporaryDirectory() as td:
            status = producer_admission_status(Path(td))
            self.assertFalse(status["ready"])
            self.assertIn("UNREADABLE", status["reason"])


if __name__ == "__main__":
    unittest.main()
