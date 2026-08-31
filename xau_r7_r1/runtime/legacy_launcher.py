from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "r7_runtime" / "frozen_parent" / "START_XAU_R6_ORIGINAL.bat.txt"
TEMP = ROOT / "__R6_PARENT_LAUNCHER_TEMP.bat"


def main() -> int:
    if os.name != "nt":
        raise RuntimeError("FROZEN_R6_LAUNCHER_IS_WINDOWS_ONLY")
    if not FROZEN.is_file():
        raise RuntimeError("FROZEN_R6_LAUNCHER_EVIDENCE_MISSING")
    if TEMP.exists():
        raise RuntimeError("TEMP_PARENT_LAUNCHER_ALREADY_EXISTS_FAIL_CLOSED")
    data = FROZEN.read_bytes()
    if not data:
        raise RuntimeError("FROZEN_R6_LAUNCHER_EMPTY")
    try:
        TEMP.write_bytes(data)
        return int(subprocess.call([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(TEMP)], cwd=str(ROOT)))
    finally:
        try:
            TEMP.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
