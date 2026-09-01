from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from r7_runtime import r6_producer_replay as replay_mod
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
            self.assertFalse(report["imports_allowed"])
            self.assertFalse(report["dunder_access_allowed"])
            self.assertFalse(report["while_loops_allowed"])
            self.assertTrue(report["range_is_bounded"])
            self.assertTrue(report["execution_line_budget_enforced"])
            self.assertEqual(report["producer_input_mutation_count"], 0)

    def test_any_import_is_forbidden(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for source in (
                'import os\ndef produce(prefix):\n    return prefix["decision"]\n',
                'import pandas as pd\ndef produce(prefix):\n    return prefix["decision"]\n',
                'from math import sqrt\ndef produce(prefix):\n    return prefix["decision"]\n',
            ):
                module = self.write_module(root, source)
                with self.assertRaisesRegex(ProducerReplayError, "PRODUCER_IMPORT_FORBIDDEN"):
                    verify_producer_source_policy(module)

    def test_dunder_attribute_escape_is_forbidden(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module = self.write_module(root, 'def produce(prefix):\n    x = prefix.__class__\n    return None\n')
            with self.assertRaisesRegex(ProducerReplayError, "PRODUCER_DUNDER_ATTRIBUTE_FORBIDDEN"):
                verify_producer_source_policy(module)

    def test_class_and_global_state_constructs_are_forbidden(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module = self.write_module(root, 'class X:\n    pass\ndef produce(prefix):\n    return None\n')
            with self.assertRaisesRegex(ProducerReplayError, "PRODUCER_TOP_LEVEL_EXECUTION_FORBIDDEN|PRODUCER_STATEFUL_CONSTRUCT_FORBIDDEN"):
                verify_producer_source_policy(module)
            module = self.write_module(root, 'COUNTER = 0\ndef produce(prefix):\n    global COUNTER\n    return None\n')
            with self.assertRaisesRegex(ProducerReplayError, "PRODUCER_STATEFUL_CONSTRUCT_FORBIDDEN"):
                verify_producer_source_policy(module)

    def test_unbounded_while_loop_is_forbidden_before_execution(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module = self.write_module(
                root,
                'def produce(prefix):\n'
                '    while True:\n'
                '        pass\n',
            )
            with self.assertRaisesRegex(ProducerReplayError, "PRODUCER_UNBOUNDED_WHILE_FORBIDDEN"):
                verify_producer_source_policy(module)

    def test_execution_line_budget_stops_large_python_loop(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module = self.write_module(
                root,
                'def produce(prefix):\n'
                '    total = 0\n'
                '    for i in range(1000):\n'
                '        total += i\n'
                '    return {"total": total}\n',
            )
            fixtures = self.write_fixture(root)
            with mock.patch.object(replay_mod, "MAX_EXECUTION_LINE_EVENTS", 25):
                with self.assertRaisesRegex(ProducerReplayError, "PRODUCER_EXECUTION_BUDGET_EXCEEDED:fx"):
                    replay_producer(fixtures, module)

    def test_range_builtin_is_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module = self.write_module(
                root,
                'def produce(prefix):\n'
                '    return {"total": sum(range(11))}\n',
            )
            fixtures = self.write_fixture(root)
            with mock.patch.object(replay_mod, "MAX_RANGE_ITEMS", 10):
                with self.assertRaisesRegex(ProducerReplayError, "PRODUCER_RANGE_LIMIT_EXCEEDED"):
                    replay_producer(fixtures, module)

    def test_fixture_input_depth_is_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module = self.write_module(root, 'def produce(prefix):\n    return None\n')
            nested = {"value": 1}
            for _ in range(6):
                nested = {"nested": nested}
            fixtures = self.write_fixture(root, nested)
            with mock.patch.object(replay_mod, "MAX_INPUT_DEPTH", 3):
                with self.assertRaisesRegex(ProducerReplayError, "FIXTURE_INPUT_DEPTH_LIMIT_EXCEEDED"):
                    replay_producer(fixtures, module)

    def test_fixture_count_is_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module = self.write_module(root, 'def produce(prefix):\n    return None\n')
            path = root / "fixtures.jsonl"
            rows = []
            for i in range(2):
                rows.append({
                    "schema": FIXTURE_SCHEMA,
                    "fixture_id": "fx" + str(i),
                    "available_through_ms": 1_700_000_001_000 + i,
                    "producer_input": {"value": i},
                })
            path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
            with mock.patch.object(replay_mod, "MAX_FIXTURE_COUNT", 1):
                with self.assertRaisesRegex(ProducerReplayError, "FIXTURE_COUNT_LIMIT_EXCEEDED"):
                    replay_producer(path, module)

    def test_producer_source_size_is_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module = self.write_module(
                root,
                'def produce(prefix):\n    return None\n' + ('# padding\n' * 20),
            )
            with mock.patch.object(replay_mod, "MAX_PRODUCER_SOURCE_BYTES", 32):
                with self.assertRaisesRegex(ProducerReplayError, "PRODUCER_SOURCE_SIZE_INVALID"):
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

    def test_nondeterministic_mutable_default_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module = self.write_module(
                root,
                'def helper(state=[0]):\n'
                '    state[0] += 1\n'
                '    return state[0]\n'
                'def produce(prefix):\n'
                '    return {"n": helper()}\n',
            )
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

    def test_non_whitelisted_builtin_is_unavailable_at_replay(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            module = self.write_module(root, 'def produce(prefix):\n    return {"x": id(prefix)}\n')
            fixtures = self.write_fixture(root)
            with self.assertRaisesRegex(ProducerReplayError, "PRODUCER_EXECUTION_FAILED:fx:NameError"):
                replay_producer(fixtures, module)


if __name__ == "__main__":
    unittest.main()
