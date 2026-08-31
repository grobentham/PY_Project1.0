from __future__ import annotations

import re
import unittest
from pathlib import Path


class LauncherCertificationSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        candidates = (
            root / "START_XAU.bat",
            root / "START_XAU_R7_R1.bat.template",
        )
        cls.launcher_path = next((p for p in candidates if p.is_file()), None)
        if cls.launcher_path is None:
            raise AssertionError("launcher template/package launcher missing from test root")
        cls.text = cls.launcher_path.read_text(encoding="utf-8", errors="strict").replace("\r\n", "\n")
        if ":PRODUCER_MENU" not in cls.text:
            raise AssertionError("producer certification submenu missing")
        cls.producer = cls.text.split(":PRODUCER_MENU", 1)[1].split(":PAUSEMENU", 1)[0]

    def test_producer_toolkit_has_integrity_verifier(self) -> None:
        self.assertIn(":VERIFY_PRODUCER_TOOLKIT", self.text)
        verifier = self.text.split(":VERIFY_PRODUCER_TOOLKIT", 1)[1]
        self.assertIn("-m r7_runtime.runtime --offline-status", verifier)
        self.assertIn("if errorlevel 1", verifier)
        self.assertIn("Producer tools will not run", verifier)

    def test_entry_and_all_four_tools_are_integrity_gated(self) -> None:
        # One gate before entering the submenu and one immediately before each
        # of the four certification tools.
        self.assertGreaterEqual(self.text.count("call :VERIFY_PRODUCER_TOOLKIT"), 5)
        entry = re.search(r'if "%CHOICE%"=="8" \((.*?)\n\)', self.text, re.S)
        self.assertIsNotNone(entry)
        self.assertIn("call :VERIFY_PRODUCER_TOOLKIT", entry.group(1))
        self.assertIn("if errorlevel 1", entry.group(1))

        for choice in ("1", "2", "3", "4"):
            block = re.search(rf'if "%PCHOICE%"=="{choice}" \((.*?)\n\)', self.producer, re.S)
            self.assertIsNotNone(block, f"producer choice {choice} block missing")
            body = block.group(1)
            gate_pos = body.find("call :VERIFY_PRODUCER_TOOLKIT")
            action_pos = body.find("powershell.exe")
            self.assertGreaterEqual(gate_pos, 0, f"producer choice {choice} missing integrity gate")
            self.assertGreater(action_pos, gate_pos, f"producer choice {choice} can act before integrity gate")
            self.assertIn("if errorlevel 1", body)

    def test_certification_submenu_has_no_direct_trading_authority(self) -> None:
        lowered = self.producer.lower()
        forbidden = (
            "order_send",
            "--run",
            "--process-r6-inbox",
            "xau_r7_r1_enable_demo_execution=yes_i_accept_demo_only",
            "causal_r6_producer_ready=true",
        )
        for token in forbidden:
            self.assertNotIn(token, lowered)

    def test_certification_actions_are_exact_hash_covered_tool_names(self) -> None:
        expected = {
            "PROBE_CANONICAL_R6_SOURCE.ps1",
            "EXTRACT_CANONICAL_R6_PRODUCER_SOURCE.ps1",
            "SEAL_R6_PRODUCER_CANDIDATE.ps1",
            "PRECHECK_R6_FUSED_RELEASE.ps1",
        }
        invoked = set(re.findall(r'-File "%CD%\\([^"\\]+\.ps1)"', self.producer, re.I))
        self.assertEqual(invoked, expected)


if __name__ == "__main__":
    unittest.main()
