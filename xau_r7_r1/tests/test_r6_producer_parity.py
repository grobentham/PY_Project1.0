from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from r7_runtime.constants import (
    CANONICAL_R6_ZIP_SHA256,
    R6_DECISION_POLICY,
    R6_DECISION_SCHEMA,
    R6_SOURCE_PRIORITY,
)
from r7_runtime.r6_integrity import sha256_file
from r7_runtime.r6_producer_parity import (
    ISOLATION_SCHEMA,
    ProducerParityError,
    build_parity_report,
)


class ProducerParityTests(unittest.TestCase):
    @staticmethod
    def decision(source: str, i: int):
        signal = 1_700_000_000_000 + i * 60_000
        return {
            "schema": R6_DECISION_SCHEMA,
            "policy": R6_DECISION_POLICY,
            "parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
            "decision_id": "fixture_" + str(i),
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

    def build_files(self, root: Path):
        sources = sorted(R6_SOURCE_PRIORITY, key=R6_SOURCE_PRIORITY.get)
        reference_rows, producer_rows = [], []
        for i, source in enumerate(sources):
            d = self.decision(source, i)
            cutoff = d["signal_bar_ms"]
            reference_rows.append({"fixture_id": "fx_" + str(i), "available_through_ms": cutoff, "decision": d})
            producer_rows.append({"fixture_id": "fx_" + str(i), "available_through_ms": cutoff, "decision": dict(d)})

        reference = root / "reference.jsonl"
        producer = root / "producer.jsonl"
        reference.write_text("\n".join(json.dumps(x, sort_keys=True) for x in reference_rows) + "\n", encoding="utf-8")
        producer.write_text("\n".join(json.dumps(x, sort_keys=True) for x in producer_rows) + "\n", encoding="utf-8")
        probe = root / "probe.json"
        probe.write_text('{"probe":"bound-by-hash"}\n', encoding="utf-8")
        module = root / "r7_runtime" / "r6_causal_producer.py"
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text("def produce(x):\n    return x\n", encoding="utf-8")
        isolation = root / "isolation.json"
        isolation.write_text(json.dumps({
            "schema": ISOLATION_SCHEMA,
            "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
            "reference_stream_sha256": sha256_file(reference),
            "producer_stream_sha256": sha256_file(producer),
            "fixture_count": len(reference_rows),
            "causal_prefix_fixture_generation": True,
            "future_rows_available_to_producer": False,
            "outcome_columns_present": False,
            "final_holdout_accessed": False,
            "strategy_retuned": False,
        }), encoding="utf-8")
        return reference, producer, isolation, probe, module

    def report(self, root: Path):
        reference, producer, isolation, probe, module = self.build_files(root)
        report = build_parity_report(
            reference,
            producer,
            isolation_path=isolation,
            source_probe_path=probe,
            producer_module_path=module,
            producer_module_relative="r7_runtime/r6_causal_producer.py",
        )
        return report, reference, producer, isolation, probe, module

    def test_exact_full_source_coverage_passes(self):
        with tempfile.TemporaryDirectory() as td:
            report, reference, producer, isolation, probe, module = self.report(Path(td))
            self.assertTrue(report["parity_pass"])
            self.assertEqual(report["mismatch_count"], 0)
            self.assertEqual(report["lookahead_violations"], 0)
            self.assertEqual(set(report["frozen_sources_covered"]), set(R6_SOURCE_PRIORITY))
            self.assertEqual(report["reference_stream_sha256"], sha256_file(reference))
            self.assertEqual(report["producer_stream_sha256"], sha256_file(producer))
            self.assertEqual(report["isolation_manifest_sha256"], sha256_file(isolation))
            self.assertEqual(report["source_probe_sha256"], sha256_file(probe))
            self.assertEqual(report["producer_module_sha256"], sha256_file(module))

    def test_selection_mismatch_produces_failing_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reference, producer, isolation, probe, module = self.build_files(root)
            rows = [json.loads(x) for x in producer.read_text(encoding="utf-8").splitlines()]
            rows[0]["decision"]["side"] *= -1
            producer.write_text("\n".join(json.dumps(x, sort_keys=True) for x in rows) + "\n", encoding="utf-8")
            iso = json.loads(isolation.read_text(encoding="utf-8"))
            iso["producer_stream_sha256"] = sha256_file(producer)
            isolation.write_text(json.dumps(iso), encoding="utf-8")
            report = build_parity_report(
                reference, producer, isolation_path=isolation, source_probe_path=probe,
                producer_module_path=module, producer_module_relative="r7_runtime/r6_causal_producer.py"
            )
            self.assertFalse(report["parity_pass"])
            self.assertEqual(report["mismatch_count"], 1)
            self.assertFalse(report["signal_selection_parity"])

    def test_signal_after_prefix_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reference, producer, isolation, probe, module = self.build_files(root)
            ref_rows = [json.loads(x) for x in reference.read_text(encoding="utf-8").splitlines()]
            prod_rows = [json.loads(x) for x in producer.read_text(encoding="utf-8").splitlines()]
            ref_rows[0]["available_through_ms"] -= 1
            prod_rows[0]["available_through_ms"] -= 1
            reference.write_text("\n".join(json.dumps(x, sort_keys=True) for x in ref_rows) + "\n", encoding="utf-8")
            producer.write_text("\n".join(json.dumps(x, sort_keys=True) for x in prod_rows) + "\n", encoding="utf-8")
            iso = json.loads(isolation.read_text(encoding="utf-8"))
            iso["reference_stream_sha256"] = sha256_file(reference)
            iso["producer_stream_sha256"] = sha256_file(producer)
            isolation.write_text(json.dumps(iso), encoding="utf-8")
            report = build_parity_report(
                reference, producer, isolation_path=isolation, source_probe_path=probe,
                producer_module_path=module, producer_module_relative="r7_runtime/r6_causal_producer.py"
            )
            self.assertFalse(report["parity_pass"])
            self.assertGreater(report["lookahead_violations"], 0)

    def test_isolation_future_rows_available_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reference, producer, isolation, probe, module = self.build_files(root)
            iso = json.loads(isolation.read_text(encoding="utf-8"))
            iso["future_rows_available_to_producer"] = True
            isolation.write_text(json.dumps(iso), encoding="utf-8")
            with self.assertRaisesRegex(ProducerParityError, "PARITY_ISOLATION_GUARD_FAILED"):
                build_parity_report(
                    reference, producer, isolation_path=isolation, source_probe_path=probe,
                    producer_module_path=module, producer_module_relative="r7_runtime/r6_causal_producer.py"
                )

    def test_isolation_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reference, producer, isolation, probe, module = self.build_files(root)
            rows = [json.loads(x) for x in producer.read_text(encoding="utf-8").splitlines()]
            rows[0]["decision"]["emitted_at_ms"] += 1
            producer.write_text("\n".join(json.dumps(x, sort_keys=True) for x in rows) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ProducerParityError, "PARITY_ISOLATION_PRODUCER_HASH_MISMATCH"):
                build_parity_report(
                    reference, producer, isolation_path=isolation, source_probe_path=probe,
                    producer_module_path=module, producer_module_relative="r7_runtime/r6_causal_producer.py"
                )

    def test_fixture_set_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reference, producer, isolation, probe, module = self.build_files(root)
            rows = producer.read_text(encoding="utf-8").splitlines()[:-1]
            producer.write_text("\n".join(rows) + "\n", encoding="utf-8")
            iso = json.loads(isolation.read_text(encoding="utf-8"))
            iso["producer_stream_sha256"] = sha256_file(producer)
            iso["fixture_count"] -= 1
            isolation.write_text(json.dumps(iso), encoding="utf-8")
            with self.assertRaisesRegex(ProducerParityError, "PARITY_FIXTURE_SET_MISMATCH"):
                build_parity_report(
                    reference, producer, isolation_path=isolation, source_probe_path=probe,
                    producer_module_path=module, producer_module_relative="r7_runtime/r6_causal_producer.py"
                )


if __name__ == "__main__":
    unittest.main()
