from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

from r7_runtime.r6_source_bundle import (
    BUNDLE_VERSION,
    OWNERSHIP_MARKER_NAME,
    R6SourceBundleError,
    extract_canonical_source_bundle,
)


R6_ENGINE = (
    'from v16r5.engine import build_r5_universe, simulate_r5, summary, component_audit\n'
    'RETIRED_SOURCE = "AUX_RF_LTM"\n'
    'def build_r6_universe(root):\n    return build_r5_universe(root)\n\n'
    'def build_r6(root, **kwargs):\n    return simulate_r5(root, **kwargs)\n'
)
R5_ENGINE = (
    'import pandas as pd\n'
    'from .helpers import feature\n'
    'from v16r5.selector import select\n'
    'def build_r5_universe(root):\n    return select(feature(root))\n\n'
    'def simulate_r5(universe, **kwargs):\n    return universe\n\n'
    'def summary(value):\n    return value\n\n'
    'def component_audit(value):\n    return value\n'
)
R5_MAIN = 'from v16r5.engine import build_r5_universe\nFROZEN = True\n'
HELPERS = 'from common.math_tools import clamp\ndef feature(root):\n    return clamp(root)\n'
SELECTOR = 'def select(value):\n    return value\n'
MATH_TOOLS = 'def clamp(value):\n    return value\n'


class SourceBundleTests(unittest.TestCase):
    def base_members(self):
        return {
            "v16r6/engine.py": R6_ENGINE.encode("utf-8"),
            "v16r5/__init__.py": b"",
            "v16r5/engine.py": R5_ENGINE.encode("utf-8"),
            "v16r5/helpers.py": HELPERS.encode("utf-8"),
            "v16r5/selector.py": SELECTOR.encode("utf-8"),
            "common/__init__.py": b"",
            "common/math_tools.py": MATH_TOOLS.encode("utf-8"),
            "V16_R5_MAIN.py": R5_MAIN.encode("utf-8"),
            "research_consumed_validation/OUTCOME_ROWS.csv": b"secret,outcome\n1,999\n",
            "research_consumed_validation/unrelated_research.py": b"SHOULD_NOT_BE_EXTRACTED=True\n",
        }

    def make_zip(self, root: Path, *, extra=None, missing=None, duplicate=None, symlink=None) -> Path:
        path = root / "parent.zip"
        members = self.base_members()
        if missing:
            members.pop(missing, None)
        if extra:
            members.update(extra)
        if symlink:
            members.pop(symlink, None)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, data in members.items():
                zf.writestr(name, data)
            if duplicate:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    zf.writestr(duplicate, members[duplicate])
            if symlink:
                info = zipfile.ZipInfo(symlink)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                zf.writestr(info, "target.py")
        return path

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def extract(self, parent: Path, out: Path, **kwargs):
        return extract_canonical_source_bundle(
            parent,
            out,
            expected_parent_sha256=self.digest(parent),
            **kwargs,
        )

    def test_extracts_local_python_dependency_closure_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = self.make_zip(root)
            out = root / "bundle"
            result = self.extract(parent, out)
            expected = {
                "v16r6/engine.py",
                "v16r5/__init__.py",
                "v16r5/engine.py",
                "v16r5/helpers.py",
                "v16r5/selector.py",
                "common/__init__.py",
                "common/math_tools.py",
                "V16_R5_MAIN.py",
            }
            self.assertEqual(result["bundle_version"], BUNDLE_VERSION)
            self.assertEqual(BUNDLE_VERSION, "R7_R1_R6_SOURCE_BUNDLE_V4")
            self.assertTrue(result["source_only_bundle"])
            self.assertTrue(result["static_local_python_dependency_closure_extracted"])
            self.assertTrue(result["required_local_imports_resolved"])
            self.assertFalse(result["dynamic_imports_allowed"])
            self.assertFalse(result["prohibited_source_paths_allowed"])
            self.assertTrue(result["owned_output_replacement_only"])
            self.assertEqual(set(result["files"]), expected)
            self.assertEqual(result["dependency_count"], len(expected))
            self.assertFalse(result["strategy_executed"])
            self.assertFalse(result["final_holdout_accessed"])
            self.assertFalse(result["producer_admitted"])
            self.assertIn("v16r5/engine.py", result["unresolved_nonarchive_imports"])
            self.assertIn("import pandas", result["unresolved_nonarchive_imports"]["v16r5/engine.py"])
            for relative in expected:
                self.assertTrue((out / relative).is_file(), relative)
            self.assertFalse((out / "research_consumed_validation").exists())
            marker = out / OWNERSHIP_MARKER_NAME
            self.assertTrue(marker.is_file())
            self.assertEqual(result["ownership_marker_file"], OWNERSHIP_MARKER_NAME)
            self.assertEqual(result["ownership_marker_sha256"], hashlib.sha256(marker.read_bytes()).hexdigest())
            probe = json.loads((out / "R7_R1_R6_SOURCE_PROBE.json").read_text(encoding="utf-8"))
            self.assertTrue(probe["required_engine_contract_present"])
            self.assertTrue(probe["normalized_ast_source_included"])
            manifest = json.loads((out / "R7_R1_R6_SOURCE_BUNDLE_MANIFEST.json").read_text(encoding="utf-8"))
            self.assertEqual(set(manifest["dependency_closure_files"]), expected)
            self.assertEqual(set(manifest["files"]), expected)
            self.assertEqual(manifest["ownership_marker_sha256"], result["ownership_marker_sha256"])

    def test_owned_output_can_be_replaced_safely(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = self.make_zip(root)
            out = root / "bundle"
            first = self.extract(parent, out)
            stale = out / "stale.tmp"
            stale.write_text("old", encoding="utf-8")
            second = self.extract(parent, out)
            self.assertFalse(stale.exists())
            self.assertEqual(first["canonical_parent_zip_sha256"], second["canonical_parent_zip_sha256"])
            self.assertTrue((out / OWNERSHIP_MARKER_NAME).is_file())

    def test_unowned_existing_directory_is_never_deleted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = self.make_zip(root)
            out = root / "important_user_folder"
            out.mkdir()
            important = out / "do_not_delete.txt"
            important.write_text("keep-me", encoding="utf-8")
            with self.assertRaisesRegex(R6SourceBundleError, "R6_SOURCE_BUNDLE_OUTPUT_NOT_OWNED"):
                self.extract(parent, out)
            self.assertEqual(important.read_text(encoding="utf-8"), "keep-me")

    def test_corrupt_ownership_marker_does_not_authorize_replacement(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = self.make_zip(root)
            out = root / "bundle"
            self.extract(parent, out)
            (out / OWNERSHIP_MARKER_NAME).write_text('{"owner_magic":"fake"}\n', encoding="utf-8")
            protected = out / "keep.txt"
            protected.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(R6SourceBundleError, "R6_SOURCE_BUNDLE_OWNERSHIP_MARKER_MISMATCH"):
                self.extract(parent, out)
            self.assertTrue(protected.is_file())

    @unittest.skipIf(os.name == "nt", "symlink creation may require Windows developer/admin privileges")
    def test_output_symlink_is_rejected_without_touching_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = self.make_zip(root)
            target = root / "target"
            target.mkdir()
            important = target / "important.txt"
            important.write_text("safe", encoding="utf-8")
            link = root / "bundle"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(R6SourceBundleError, "R6_SOURCE_BUNDLE_OUTPUT_SYMLINK_FORBIDDEN"):
                self.extract(parent, link)
            self.assertEqual(important.read_text(encoding="utf-8"), "safe")

    def test_third_party_import_is_recorded_not_falsely_extracted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = self.make_zip(root)
            out = root / "bundle"
            result = self.extract(parent, out)
            self.assertNotIn("pandas.py", result["files"])
            self.assertFalse((out / "pandas.py").exists())
            self.assertIn("import pandas", result["unresolved_nonarchive_imports"]["v16r5/engine.py"])

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
                self.extract(parent, root / "bundle")

    def test_missing_relative_local_helper_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = self.make_zip(root, missing="v16r5/helpers.py")
            with self.assertRaisesRegex(R6SourceBundleError, "R6_SOURCE_REQUIRED_LOCAL_IMPORT_MISSING"):
                self.extract(parent, root / "bundle")

    def test_missing_absolute_module_under_local_package_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = self.make_zip(root, missing="v16r5/selector.py")
            with self.assertRaisesRegex(R6SourceBundleError, "R6_SOURCE_REQUIRED_LOCAL_IMPORT_MISSING"):
                self.extract(parent, root / "bundle")

    def test_duplicate_archive_member_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = self.make_zip(root, duplicate="v16r6/engine.py")
            with self.assertRaisesRegex(R6SourceBundleError, "R6_ZIP_DUPLICATE_MEMBER"):
                self.extract(parent, root / "bundle")

    def test_unsafe_archive_member_fails_even_when_not_selected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = self.make_zip(root, extra={"../escape.txt": b"nope"})
            with self.assertRaisesRegex(R6SourceBundleError, "R6_ZIP_UNSAFE_MEMBER_PATH"):
                self.extract(parent, root / "bundle")
            self.assertFalse((root / "escape.txt").exists())

    def test_non_utf8_protected_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = self.make_zip(root, extra={"v16r6/engine.py": b"\xff\xfe\xfd"})
            with self.assertRaisesRegex(R6SourceBundleError, "R6_ZIP_SOURCE_NOT_UTF8"):
                self.extract(parent, root / "bundle")

    def test_imported_symlink_source_is_forbidden(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent = self.make_zip(root, symlink="v16r5/helpers.py")
            with self.assertRaisesRegex(R6SourceBundleError, "R6_SOURCE_DEPENDENCY_SYMLINK_FORBIDDEN"):
                self.extract(parent, root / "bundle")

    def test_prohibited_validation_or_holdout_local_dependency_fails_before_output(self):
        cases = (
            ("research_consumed_validation", "research_consumed_validation.secret"),
            ("final_holdout", "final_holdout.secret"),
            ("protected_validation", "protected_validation.secret"),
            ("retrospective_research", "retrospective_research.secret"),
        )
        for folder, module in cases:
            with self.subTest(folder=folder), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                helper = (f"from {module} import leak\ndef feature(root):\n    return leak(root)\n").encode("utf-8")
                parent = self.make_zip(root, extra={
                    "v16r5/helpers.py": helper,
                    f"{folder}/__init__.py": b"",
                    f"{folder}/secret.py": b"def leak(value):\n    return value\n",
                })
                out = root / "bundle"
                with self.assertRaisesRegex(R6SourceBundleError, "R6_SOURCE_PROHIBITED_PATH"):
                    self.extract(parent, out)
                self.assertFalse(out.exists())

    def test_dynamic_import_in_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dynamic = (
                'import importlib\n'
                'def feature(root):\n'
                '    importlib.import_module("hidden_plugin")\n'
                '    return root\n'
            ).encode("utf-8")
            parent = self.make_zip(root, extra={"v16r5/helpers.py": dynamic})
            with self.assertRaisesRegex(R6SourceBundleError, "R6_SOURCE_DYNAMIC_IMPORT_UNRESOLVED"):
                self.extract(parent, root / "bundle")

    def test_aliased_dynamic_imports_fail_closed(self):
        sources = (
            'import importlib as il\ndef feature(root):\n    il.import_module("hidden")\n    return root\n',
            'from importlib import import_module as im\ndef feature(root):\n    im("hidden")\n    return root\n',
            'import importlib\nloader = importlib.import_module\ndef feature(root):\n    loader("hidden")\n    return root\n',
            'import builtins as b\ndef feature(root):\n    b.__import__("hidden")\n    return root\n',
        )
        for index, source in enumerate(sources):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                parent = self.make_zip(root, extra={"v16r5/helpers.py": source.encode("utf-8")})
                with self.assertRaisesRegex(R6SourceBundleError, "R6_SOURCE_DYNAMIC_IMPORT_UNRESOLVED"):
                    self.extract(parent, root / "bundle")

    def test_reflective_dynamic_import_reconstruction_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dynamic = (
                'import importlib\n'
                'def feature(root):\n'
                '    loader = getattr(importlib, "import_module")\n'
                '    loader("hidden")\n'
                '    return root\n'
            ).encode("utf-8")
            parent = self.make_zip(root, extra={"v16r5/helpers.py": dynamic})
            with self.assertRaisesRegex(R6SourceBundleError, "R6_SOURCE_DYNAMIC_IMPORT_UNRESOLVED"):
                self.extract(parent, root / "bundle")


if __name__ == "__main__":
    unittest.main()
