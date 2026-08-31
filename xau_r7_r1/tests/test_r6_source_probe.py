from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from r7_runtime.r6_source_probe import R6SourceProbeError, probe_frozen_r6_source


R6 = '''\
from v16r5.engine import build_r5_universe, simulate_r5, summary, component_audit
RETIRED_SOURCE = "AUX_RF_LTM"

def build_r6_universe(root):
    return build_r5_universe(root)

def build_r6(root, **kwargs):
    u, info = build_r6_universe(root)
    return simulate_r5(u, **kwargs)
'''

R5 = '''\
THRESHOLD = 0.975

def build_r5_universe(root):
    return [], {"threshold": THRESHOLD}

def simulate_r5(universe, fallback_map=None, **kwargs):
    return []

def summary(trades):
    return {}

def component_audit(trades):
    return {}
'''

MAIN = '''\
def main():
    return 0
'''


class R6SourceProbeTests(unittest.TestCase):
    def make_tree(self, root: Path):
        (root / "v16r6").mkdir(parents=True)
        (root / "v16r5").mkdir(parents=True)
        (root / "v16r6" / "engine.py").write_text(R6, encoding="utf-8")
        (root / "v16r5" / "engine.py").write_text(R5, encoding="utf-8")
        (root / "V16_R5_MAIN.py").write_text(MAIN, encoding="utf-8")

    def test_exact_source_contract_probe_passes_without_execution(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.make_tree(root)
            report = probe_frozen_r6_source(root)
            self.assertTrue(report["source_only_probe"])
            self.assertTrue(report["normalized_ast_source_included"])
            self.assertTrue(report["required_engine_contract_present"])
            self.assertFalse(report["producer_admitted"])
            self.assertFalse(report["final_holdout_accessed"])
            self.assertFalse(report["strategy_executed"])
            r6_functions = {f["name"] for f in report["files"]["v16r6/engine.py"]["functions"]}
            self.assertEqual({"build_r6_universe", "build_r6"}, r6_functions)

    def test_probe_exports_normalized_source_call_graph_and_ast_hashes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.make_tree(root)
            report = probe_frozen_r6_source(root)
            r6 = report["files"]["v16r6/engine.py"]
            by_name = {f["name"]: f for f in r6["functions"]}
            build = by_name["build_r6"]
            self.assertIn("build_r6_universe", build["calls"])
            self.assertIn("simulate_r5", build["calls"])
            self.assertIn("return simulate_r5", build["normalized_source"])
            self.assertEqual(len(build["ast_sha256"]), 64)
            self.assertGreater(build["lineno"], 0)
            self.assertGreaterEqual(build["end_lineno"], build["lineno"])
            self.assertEqual(r6["assigned_expressions"]["RETIRED_SOURCE"], "'AUX_RF_LTM'")
            self.assertEqual(report["files"]["v16r5/engine.py"]["assigned_expressions"]["THRESHOLD"], "0.975")

    def test_missing_required_r5_function_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.make_tree(root)
            (root / "v16r5" / "engine.py").write_text("def build_r5_universe(root):\n    return [], {}\n", encoding="utf-8")
            with self.assertRaisesRegex(R6SourceProbeError, "R6_REQUIRED_ENGINE_FUNCTIONS_MISSING"):
                probe_frozen_r6_source(root)

    def test_missing_retired_source_assignment_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.make_tree(root)
            (root / "v16r6" / "engine.py").write_text(R6.replace('RETIRED_SOURCE = "AUX_RF_LTM"\n', ''), encoding="utf-8")
            with self.assertRaisesRegex(R6SourceProbeError, "R6_RETIRED_SOURCE_ASSIGNMENT_MISSING"):
                probe_frozen_r6_source(root)

    def test_path_escape_or_missing_source_cannot_be_silently_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.make_tree(root)
            (root / "V16_R5_MAIN.py").unlink()
            with self.assertRaisesRegex(R6SourceProbeError, "R6_SOURCE_FILE_MISSING"):
                probe_frozen_r6_source(root)


if __name__ == "__main__":
    unittest.main()
