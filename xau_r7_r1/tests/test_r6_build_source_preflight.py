from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from r7_runtime.r6_build_source_preflight import (
    PREFLIGHT_VERSION,
    preflight_canonical_source,
)
from r7_runtime.r6_source_bundle import R6SourceBundleError


R6_ENGINE = (
    'from v16r5.engine import build_r5_universe, simulate_r5, summary, component_audit\n'
    'RETIRED_SOURCE = "AUX_RF_LTM"\n'
    'def build_r6_universe(root):\n    return build_r5_universe(root)\n\n'
    'def build_r6(root, **kwargs):\n    return simulate_r5(root, **kwargs)\n'
)
R5_ENGINE = (
    'import pandas as pd\n'
    'from .helpers import feature\n'
    'def build_r5_universe(root):\n    return feature(root)\n\n'
    'def simulate_r5(universe, **kwargs):\n    return universe\n\n'
    'def summary(value):\n    return value\n\n'
    'def component_audit(value):\n    return value\n'
)
R5_MAIN = 'from v16r5.engine import build_r5_universe\nFROZEN = True\n'
HELPERS = 'def feature(root):\n    return root\n'


class CanonicalSourceBuildPreflightTests(unittest.TestCase):
    def make_parent(self, root: Path) -> Path:
        path = root / "parent.zip"
        members = {
            "v16r6/engine.py": R6_ENGINE,
            "v16r5/__init__.py": "",
            "v16r5/engine.py": R5_ENGINE,
            "v16r5/helpers.py": HELPERS,
            "V16_R5_MAIN.py": R5_MAIN,
            "research_consumed_validation/OUTCOME_ROWS.csv": "secret,outcome\n1,999\n",
            "V16_R6_FINAL_HOLDOUT_PREREGISTRATION.json": '{"untouched":true}\n',
        }
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, text in members.items():
                zf.writestr(name, text.encode("utf-8"))
        return path

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_preflight_exercises_source_closure_without_outcome_extraction(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = self.make_parent(root)
            expected = self.digest(parent)
            out = root / "source_preflight"
            result = preflight_canonical_source(
                parent,
                out,
                expected_parent_sha256=expected,
            )
            self.assertEqual(result["preflight_version"], PREFLIGHT_VERSION)
            self.assertEqual(result["canonical_parent_zip_sha256"], expected)
            self.assertTrue(result["source_only_bundle_verified"])
            self.assertTrue(result["dependency_closure_verified"])
            self.assertTrue(result["required_engine_contract_verified"])
            self.assertGreaterEqual(result["dependency_count"], 4)
            self.assertGreaterEqual(result["unresolved_nonarchive_import_count"], 1)
            self.assertFalse(result["strategy_executed"])
            self.assertFalse(result["strategy_retuned"])
            self.assertFalse(result["final_holdout_accessed"])
            self.assertFalse(result["producer_admitted"])
            self.assertFalse((out / "research_consumed_validation").exists())
            self.assertFalse((out / "V16_R6_FINAL_HOLDOUT_PREREGISTRATION.json").exists())
            self.assertTrue((out / "v16r6" / "engine.py").is_file())
            self.assertTrue((out / "v16r5" / "engine.py").is_file())
            self.assertTrue((out / "V16_R5_MAIN.py").is_file())
            serialized = json.dumps(result, sort_keys=True)
            self.assertNotIn("normalized_source", serialized)
            self.assertNotIn("OUTCOME_ROWS", serialized)

    def test_wrong_parent_hash_fails_before_source_preflight(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = self.make_parent(root)
            out = root / "source_preflight"
            with self.assertRaisesRegex(R6SourceBundleError, "CANONICAL_R6_SHA256_MISMATCH"):
                preflight_canonical_source(
                    parent,
                    out,
                    expected_parent_sha256="0" * 64,
                )
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
