from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

from r7_runtime.r6_source_bundle import R6SourceBundleError, extract_canonical_source_bundle


R6_ENGINE = (
    'RETIRED_SOURCE = "AUX_RF_LTM"\n'
    'def build_r6_universe(root):\n    return root\n\n'
    'def build_r6(root, **kwargs):\n    return root, kwargs\n'
)
R5_ENGINE = (
    'def build_r5_universe(root):\n    return root\n\n'
    'def simulate_r5(universe, **kwargs):\n    return universe\n\n'
    'def summary(value):\n    return value\n\n'
    'def component_audit(value):\n    return value\n'
)
R5_MAIN = 'FROZEN = True\n'


class SourceBundleTests(unittest.TestCase):
    def make_zip(self, root: Path, *, extra=None, missing=None, duplicate=None) -> Path:
        path = root / "parent.zip"
        members = {
            "v16r6/engine.py": R6_ENGINE.encode("utf-8"),
            "v16r5/engine.py": R5_ENGINE.encode("utf-8"),
            "V16_R5_MAIN.py": R5_MAIN.encode("utf-8"),
            "research_consumed_validation/OUTCOME_ROWS.csv": b"secret,outcome\n1,999\n",
        }
        if missing:
            members.pop(missing, None)
        if extra:
            members.update(extra)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, data in members.items():
                zf.writestr(name, data)
            if duplicate:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    zf.writestr(duplicate, members[duplicate])
        return path

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_extracts_only_required_source_and_writes_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = self.make_zip(root)
            out = root / "bundle"
            result = extract_canonical_source_bundle(
                parent, out, expected_parent_sha256=self.digest(parent)
            )
            self.assertTrue(result["source_only_bundle"])
            self.assertFalse(result["strategy_executed"])
            self.assertFalse(result["final_holdout_accessed"])
            self.assertFalse(result["producer_admitted"])
            self.assertTrue((out / "v16r6" / "engine.py").is_file())
            self.assertTrue((out / "v16r5" / "engine.py").is_file())
            self.assertTrue((out / "V16_R5_MAIN.py").is_file())
            self.assertFalse((out / "research_consumed_validation").exists())
            probe = json.loads((out / "R7_R1_R6_SOURCE_PROBE.json").read_text(encoding="utf-8"))
            self.assertTrue(probe["required_engine_contract_present"])
            manifest = json.loads((out / "R7_R1_R6_SOURCE_BUNDLE_MANIFEST.json").read_text(encoding="utf-8"))
            self.assertEqual(set(manifest["files"]), {"v16r6/engine.py", "v16r5/engine.py", "V16_R5_MAIN.py"})

    def test_wrong_parent_hash_fails_before_extraction(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = self.make_zip(root)
            out = root / "bundle"
            with self.assertRaisesRegex(R6SourceBundleError, "CANONICAL_R6_SHA256_MISMATCH"):
                extract_canonical_source_bundle(parent, out, expected_parent_sha256="0" * 64)
            self.assertFalse(out.exists())

    def test_missing_required_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = self.make_zip(root, missing="v16r5/engine.py")
            with self.assertRaisesRegex(R6SourceBundleError, "R6_ZIP_REQUIRED_SOURCE_MISSING"):
                extract_canonical_source_bundle(parent, root / "bundle", expected_parent_sha256=self.digest(parent))

    def test_duplicate_required_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = self.make_zip(root, duplicate="v16r6/engine.py")
            with self.assertRaisesRegex(R6SourceBundleError, "R6_ZIP_DUPLICATE_REQUIRED_MEMBER"):
                extract_canonical_source_bundle(parent, root / "bundle", expected_parent_sha256=self.digest(parent))

    def test_unsafe_archive_member_fails_even_when_not_selected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = self.make_zip(root, extra={"../escape.txt": b"nope"})
            with self.assertRaisesRegex(R6SourceBundleError, "R6_ZIP_UNSAFE_MEMBER_PATH"):
                extract_canonical_source_bundle(parent, root / "bundle", expected_parent_sha256=self.digest(parent))
            self.assertFalse((root / "escape.txt").exists())

    def test_non_utf8_protected_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = self.make_zip(root, extra={"v16r6/engine.py": b"\xff\xfe\xfd"})
            with self.assertRaisesRegex(R6SourceBundleError, "R6_ZIP_SOURCE_NOT_UTF8"):
                extract_canonical_source_bundle(parent, root / "bundle", expected_parent_sha256=self.digest(parent))


if __name__ == "__main__":
    unittest.main()
