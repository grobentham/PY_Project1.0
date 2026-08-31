from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from r7_runtime.r6_producer_replay import (
    FIXTURE_SCHEMA,
    ProducerReplayError,
    replay_producer,
    verify_producer_source_policy,
)


class ProducerReplayTests(unittest.TestCase):
    def write_module(self, root: Path, source: str) -> Path:
        path = root / "r6_causal_producer.py"
        path.write_text(source, encoding="utf-8")
        return path

    def write_fixture(self, root: Path, producer_input=None, cutoff=1_700_000_001_000) -> Path:
        if producer_input is None:
            producer_input = {"decision": {"signal_bar_ms": cutoff - 1000, "value": 1}}
        path = root / "fixtures.jsonl"
        path.write_text(json.dumps({
            "schema": FIXTURE_SCHEMA,
            "fixture_id": "fx",
            "available_through_ms": cutoff,
            "producer_input": producer_input,
        }, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def test_pure_deterministic_producer_replays(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module = self.write_module(root, 'def produce(prefix):\n    return prefix["decision"]\n')
            fixtures = self.write_fixture(root)
            stream, report = replay_producer(fixtures, module)
            self.assertTrue(stream.endswith(b"\n"))
            self.assertTrue(report["deterministic_double_run"])
            self.assertTrue(report["source_policy_pass"])
            self.assertEqual(report["producer_input_mutation_count"], 0)

    def test_filesystem_import_is_forbidden(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module = self.write_module(root, 'import os\ndef produce(prefix):\n    return prefix["decision"]\n')
            with self.assertRaisesRegex(ProducerReplayError, "PRODUCER_IMPORT_FORBIDDEN"):
                verify_producer_source_policy(module)

    def test_aliasing_pandas_io_attribute_is_forbidden(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module = self.write_module(root, 'import pandas as pd\ndef produce(prefix):\n    reader = pd.read_csv\n    return prefix["decision"]\n')
            with self.assertRaisesRegex(ProducerReplayError, "PRODUCER_IO_ATTRIBUTE_FORBIDDEN"):
                verify_producer_source_policy(module)

    def test_from_import_io_function_is_forbidden(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module = self.write_module(root, 'from pandas import read_csv\ndef produce(prefix):\n    return prefix["decision"]\n')
            with self.assertRaisesRegex(ProducerReplayError, "PRODUCER_IMPORT_SYMBOL_FORBIDDEN"):
                verify_producer_source_policy(module)

    def test_dunder_attribute_escape_is_forbidden(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module = self.write_module(root, 'import pandas as pd\ndef produce(prefix):\n    x = pd.__dict__\n    return prefix["decision"]\n')
            with self.assertRaisesRegex(ProducerReplayError, "PRODUCER_DUNDER_ATTRIBUTE_FORBIDDEN"):
                verify_producer_source_policy(module)

    def test_outcome_labelled_fixture_input_is_forbidden(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module = self.write_module(root, 'def produce(prefix):\n    return None\n')
            fixtures = self.write_fixture(root, {"outcome": 1})
            with self.assertRaisesRegex(ProducerReplayError, "FIXTURE_PROHIBITED_INPUT_KEY"):
                replay_producer(fixtures, module)

    def test_fixture_timestamp_after_prefix_is_forbidden(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module = self.write_module(root, 'def produce(prefix):\n    return None\n')
            cutoff = 1_700_000_000_000
            fixtures = self.write_fixture(root, {"signal_bar_ms": cutoff + 1}, cutoff=cutoff)
            with self.assertRaisesRegex(ProducerReplayError, "FIXTURE_TIMESTAMP_AFTER_PREFIX"):
                replay_producer(fixtures, module)

    def test_nondeterministic_producer_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module = self.write_module(root, 'COUNTER = 0\ndef produce(prefix):\n    global COUNTER\n    COUNTER += 1\n    return {"n": COUNTER}\n')
            fixtures = self.write_fixture(root)
            with self.assertRaisesRegex(ProducerReplayError, "PRODUCER_NONDETERMINISTIC"):
                replay_producer(fixtures, module)

    def test_input_mutation_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module = self.write_module(root, 'def produce(prefix):\n    prefix["mutated"] = True\n    return None\n')
            fixtures = self.write_fixture(root)
            with self.assertRaisesRegex(ProducerReplayError, "PRODUCER_MUTATED_INPUT"):
                replay_producer(fixtures, module)

    def test_prohibited_holdout_literal_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module = self.write_module(root, 'NAME = "final_holdout.csv"\ndef produce(prefix):\n    return None\n')
            with self.assertRaisesRegex(ProducerReplayError, "PRODUCER_PROHIBITED_DATA_REFERENCE"):
                verify_producer_source_policy(module)


if __name__ == "__main__":
    unittest.main()
