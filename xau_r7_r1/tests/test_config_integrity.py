from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from r7_runtime.constants import CANONICAL_R6_ZIP_SHA256
from r7_runtime.r6_integrity import (
    REQUIRED_R7_OPERATOR_FILES,
    IntegrityError,
    sha256_file,
    verify_runtime_package_integrity,
)
from r7_runtime import runtime


class ConfigTests(unittest.TestCase):
    def write_config(self, root: Path, value) -> Path:
        p = root / "config.json"
        p.write_text(json.dumps(value), encoding="utf-8")
        return p

    @staticmethod
    def v5_admission_status():
        return {
            "ready": True,
            "authority_version": "R7_R1_R6_PRODUCER_ADMISSION_AUTHORITY_V5",
            "canonical_reference_replay_pass": True,
            "final_holdout_accessed": False,
            "strategy_retuned": False,
        }

    def test_valid_restrictive_config(self):
        with tempfile.TemporaryDirectory() as td:
            p = self.write_config(Path(td), {
                "max_tick_age_seconds": 2.0,
                "max_spread_usd": 0.5,
                "request_demo_execution": False,
            })
            with mock.patch.object(runtime, "CONFIG_PATH", p):
                cfg = runtime.load_config()
            self.assertEqual(cfg["max_tick_age_seconds"], 2.0)
            self.assertEqual(cfg["max_spread_usd"], 0.5)
            self.assertFalse(cfg["request_demo_execution"])

    def test_config_cannot_weaken_tick_guard(self):
        with tempfile.TemporaryDirectory() as td:
            p = self.write_config(Path(td), {"max_tick_age_seconds": 5.01})
            with mock.patch.object(runtime, "CONFIG_PATH", p):
                with self.assertRaises(RuntimeError):
                    runtime.load_config()

    def test_config_cannot_weaken_spread_guard(self):
        with tempfile.TemporaryDirectory() as td:
            p = self.write_config(Path(td), {"max_spread_usd": 1.01})
            with mock.patch.object(runtime, "CONFIG_PATH", p):
                with self.assertRaises(RuntimeError):
                    runtime.load_config()

    def test_execution_request_must_be_boolean(self):
        with tempfile.TemporaryDirectory() as td:
            p = self.write_config(Path(td), {"request_demo_execution": "false"})
            with mock.patch.object(runtime, "CONFIG_PATH", p):
                with self.assertRaises(RuntimeError):
                    runtime.load_config()

    def test_unknown_config_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = self.write_config(Path(td), {"disable_demo_only": True})
            with mock.patch.object(runtime, "CONFIG_PATH", p):
                with self.assertRaises(RuntimeError):
                    runtime.load_config()

    def test_demo_execution_remains_locked_without_causal_producer(self):
        cfg = {"request_demo_execution": True}
        env = {"XAU_R7_R1_ENABLE_DEMO_EXECUTION": "YES_I_ACCEPT_DEMO_ONLY"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(runtime.demo_execution_enabled(cfg))

    def test_readiness_switch_alone_cannot_unlock_without_admission_evidence(self):
        cfg = {"request_demo_execution": True}
        env = {"XAU_R7_R1_ENABLE_DEMO_EXECUTION": "YES_I_ACCEPT_DEMO_ONLY"}
        with mock.patch.object(runtime, "CAUSAL_R6_PRODUCER_READY", True):
            with mock.patch.object(runtime, "producer_admission_status", return_value={"ready": False, "reason": "missing parity"}):
                with mock.patch.dict(os.environ, env, clear=True):
                    self.assertFalse(runtime.producer_execution_admitted())
                    self.assertFalse(runtime.demo_execution_enabled(cfg))

    def test_v4_ready_status_cannot_bypass_v5_reference_authority(self):
        cfg = {"request_demo_execution": True}
        env = {"XAU_R7_R1_ENABLE_DEMO_EXECUTION": "YES_I_ACCEPT_DEMO_ONLY"}
        legacy_v4 = {
            "ready": True,
            "admission_version": "R7_R1_R6_PRODUCER_ADMISSION_V4",
            "final_holdout_accessed": False,
            "strategy_retuned": False,
        }
        with mock.patch.object(runtime, "CAUSAL_R6_PRODUCER_READY", True):
            with mock.patch.object(runtime, "producer_admission_status", return_value=legacy_v4):
                with mock.patch.dict(os.environ, env, clear=True):
                    self.assertFalse(runtime.producer_execution_admitted())
                    self.assertFalse(runtime.demo_execution_enabled(cfg))

    def test_v5_authority_requires_clean_reference_holdout_and_retune_flags(self):
        with mock.patch.object(runtime, "CAUSAL_R6_PRODUCER_READY", True):
            for field, value in (
                ("canonical_reference_replay_pass", False),
                ("final_holdout_accessed", True),
                ("strategy_retuned", True),
            ):
                status = self.v5_admission_status()
                status[field] = value
                with mock.patch.object(runtime, "producer_admission_status", return_value=status):
                    self.assertFalse(runtime.producer_execution_admitted(), field)

    def test_demo_execution_needs_v5_admitted_producer_config_and_exact_environment_unlock(self):
        cfg = {"request_demo_execution": True}
        with mock.patch.object(runtime, "CAUSAL_R6_PRODUCER_READY", True):
            with mock.patch.object(runtime, "producer_admission_status", return_value=self.v5_admission_status()):
                with mock.patch.dict(os.environ, {}, clear=True):
                    self.assertFalse(runtime.demo_execution_enabled(cfg))
                with mock.patch.dict(os.environ, {"XAU_R7_R1_ENABLE_DEMO_EXECUTION": "wrong"}, clear=True):
                    self.assertFalse(runtime.demo_execution_enabled(cfg))
                with mock.patch.dict(os.environ, {"XAU_R7_R1_ENABLE_DEMO_EXECUTION": "YES_I_ACCEPT_DEMO_ONLY"}, clear=True):
                    self.assertTrue(runtime.producer_execution_admitted())
                    self.assertTrue(runtime.demo_execution_enabled(cfg))


class PackageIntegrityTests(unittest.TestCase):
    def build_fake_package(self, root: Path):
        parent_paths = [
            "v16r6/engine.py",
            "v16r5/engine.py",
            "V16_R5_MAIN.py",
            "V16_R6_RESEARCH_DESIGN_LOCK.json",
            "V16_R6_FINAL_HOLDOUT_PREREGISTRATION.json",
            "START_XAU.bat",
        ]
        for rel in parent_paths:
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("PARENT:" + rel, encoding="utf-8")
        parent_hashes = {rel: sha256_file(root / rel) for rel in parent_paths}
        protected = {rel: parent_hashes[rel] for rel in parent_paths if rel != "START_XAU.bat"}
        original_launcher_hash = parent_hashes["START_XAU.bat"]
        (root / "START_XAU.bat").write_text("R7 LAUNCHER", encoding="utf-8")
        frozen = root / "r7_runtime" / "frozen_parent" / "START_XAU_R6_ORIGINAL.bat.txt"
        frozen.parent.mkdir(parents=True, exist_ok=True)
        frozen.write_text("PARENT:START_XAU.bat", encoding="utf-8")
        code = root / "r7_runtime" / "runtime.py"
        code.write_text("VERSION='TEST'", encoding="utf-8")
        r7_hashes = {
            "r7_runtime/runtime.py": sha256_file(code),
            "START_XAU.bat": sha256_file(root / "START_XAU.bat"),
        }
        operator_hashes = {}
        for rel in sorted(REQUIRED_R7_OPERATOR_FILES):
            p = root / rel
            p.write_text("R7_OPERATOR:" + rel, encoding="utf-8")
            operator_hashes[rel] = sha256_file(p)
        manifest = {
            "canonical_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
            "build_verified_parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
            "parent_tree_sha256": parent_hashes,
            "protected_r6_hashes": protected,
            "r7_runtime_code_sha256": r7_hashes,
            "r7_operator_tool_sha256": operator_hashes,
            "original_start_xau_sha256": original_launcher_hash,
            "final_holdout_accessed": False,
            "strategy_retuned": False,
            "demo_only": True,
            "execution_enabled_by_default": False,
            "causal_r6_producer_ready": False,
        }
        (root / "R7_R1_PARENT_INTEGRITY.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_full_runtime_package_integrity_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.build_fake_package(root)
            result = verify_runtime_package_integrity(root)
            self.assertEqual(result["protected_r6_files"], 5)
            self.assertEqual(result["r7_runtime_code_files"], 2)
            self.assertEqual(result["r7_operator_tool_files"], len(REQUIRED_R7_OPERATOR_FILES))

    def test_shadow_copy_of_protected_source_does_not_confuse_exact_manifest_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.build_fake_package(root)
            shadow = root / "R7_R1_R6_PRODUCER_SOURCE" / "v16r6" / "engine.py"
            shadow.parent.mkdir(parents=True, exist_ok=True)
            shadow.write_text("SOURCE_WORKSPACE_SHADOW=True\n", encoding="utf-8")
            result = verify_runtime_package_integrity(root)
            self.assertEqual(result["protected_r6_files"], 5)

    def test_causal_producer_manifest_guard_missing_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.build_fake_package(root)
            manifest_path = root / "R7_R1_PARENT_INTEGRITY.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.pop("causal_r6_producer_ready")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(IntegrityError, "CAUSAL_R6_PRODUCER_LOCK"):
                verify_runtime_package_integrity(root)

    def test_causal_producer_manifest_guard_true_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.build_fake_package(root)
            manifest_path = root / "R7_R1_PARENT_INTEGRITY.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["causal_r6_producer_ready"] = True
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(IntegrityError, "CAUSAL_R6_PRODUCER_LOCK"):
                verify_runtime_package_integrity(root)

    def test_protected_parent_tamper_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.build_fake_package(root)
            (root / "v16r6" / "engine.py").write_text("tampered", encoding="utf-8")
            with self.assertRaises(IntegrityError):
                verify_runtime_package_integrity(root)

    def test_r7_runtime_tamper_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.build_fake_package(root)
            (root / "r7_runtime" / "runtime.py").write_text("tampered", encoding="utf-8")
            with self.assertRaises(IntegrityError):
                verify_runtime_package_integrity(root)

    def test_untracked_runtime_python_file_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.build_fake_package(root)
            (root / "r7_runtime" / "untracked.py").write_text("INJECTED=True\n", encoding="utf-8")
            with self.assertRaisesRegex(IntegrityError, "R7_RUNTIME_CODE_PATH_SET_MISMATCH"):
                verify_runtime_package_integrity(root)

    def test_runtime_manifest_path_omission_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.build_fake_package(root)
            manifest_path = root / "R7_R1_PARENT_INTEGRITY.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["r7_runtime_code_sha256"].pop("r7_runtime/runtime.py")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(IntegrityError, "R7_RUNTIME_CODE_PATH_SET_MISMATCH"):
                verify_runtime_package_integrity(root)

    def test_operator_tool_tamper_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.build_fake_package(root)
            target = root / "PRECHECK_R6_FUSED_RELEASE.ps1"
            target.write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(IntegrityError, "R7_OPERATOR_TOOL_HASH_MISMATCH"):
                verify_runtime_package_integrity(root)

    def test_operator_tool_path_omission_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.build_fake_package(root)
            manifest_path = root / "R7_R1_PARENT_INTEGRITY.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["r7_operator_tool_sha256"].pop("R7_R1_REPAIR_AUDIT.md")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(IntegrityError, "R7_OPERATOR_TOOL_PATH_SET_MISMATCH"):
                verify_runtime_package_integrity(root)

    def test_frozen_original_launcher_tamper_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.build_fake_package(root)
            frozen = root / "r7_runtime" / "frozen_parent" / "START_XAU_R6_ORIGINAL.bat.txt"
            frozen.write_text("tampered", encoding="utf-8")
            with self.assertRaises(IntegrityError):
                verify_runtime_package_integrity(root)


if __name__ == "__main__":
    unittest.main()
