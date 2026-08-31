from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict

from .audit_store import AuditStore
from .constants import (
    EXECUTION_UNLOCK_ENV,
    EXECUTION_UNLOCK_VALUE,
    HARD_MAX_SPREAD_USD,
    HARD_MAX_TICK_AGE_SECONDS,
    VERSION,
)
from .execution import ExecutionEngine
from .instance_lock import SingleInstanceLock
from .models import OrderIntent
from .mt5_gateway import MT5Gateway
from .r6_integrity import verify_runtime_parent_integrity


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
DB_PATH = RUNTIME_DIR / "r7_r1_state.sqlite3"
LOCK_PATH = RUNTIME_DIR / "r7_r1_runtime.lock"
CONFIG_PATH = ROOT / "R7_R1_RUNTIME_CONFIG.json"


def load_config() -> Dict[str, Any]:
    cfg = {
        "max_tick_age_seconds": HARD_MAX_TICK_AGE_SECONDS,
        "max_spread_usd": HARD_MAX_SPREAD_USD,
        "request_demo_execution": False,
    }
    if CONFIG_PATH.exists():
        user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(user, dict):
            raise RuntimeError("R7_R1_CONFIG_INVALID")
        cfg.update(user)
    tick_age = float(cfg["max_tick_age_seconds"])
    spread = float(cfg["max_spread_usd"])
    if tick_age <= 0 or tick_age > HARD_MAX_TICK_AGE_SECONDS:
        raise RuntimeError("CONFIG_TICK_AGE_MAY_NOT_WEAKEN_HARD_GUARD")
    if spread <= 0 or spread > HARD_MAX_SPREAD_USD:
        raise RuntimeError("CONFIG_SPREAD_MAY_NOT_WEAKEN_HARD_GUARD")
    cfg["max_tick_age_seconds"] = tick_age
    cfg["max_spread_usd"] = spread
    cfg["request_demo_execution"] = bool(cfg.get("request_demo_execution", False))
    return cfg


def demo_execution_enabled(cfg: Dict[str, Any]) -> bool:
    return bool(cfg["request_demo_execution"]) and os.environ.get(EXECUTION_UNLOCK_ENV) == EXECUTION_UNLOCK_VALUE


def load_intent(path: Path) -> OrderIntent:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("INTENT_JSON_MUST_BE_OBJECT")
    allowed = {"client_intent_id", "side", "lot", "stop_price", "take_profit_price", "source"}
    unknown = set(raw) - allowed
    missing = {"client_intent_id", "side", "lot", "stop_price", "source"} - set(raw)
    if unknown:
        raise RuntimeError("INTENT_UNKNOWN_FIELDS:" + ",".join(sorted(unknown)))
    if missing:
        raise RuntimeError("INTENT_MISSING_FIELDS:" + ",".join(sorted(missing)))
    return OrderIntent(
        client_intent_id=str(raw["client_intent_id"]),
        side=str(raw["side"]),
        lot=float(raw["lot"]),
        stop_price=float(raw["stop_price"]),
        take_profit_price=None if raw.get("take_profit_price") is None else float(raw["take_profit_price"]),
        source=str(raw["source"]),
    )


def offline_status(store: AuditStore) -> Dict[str, Any]:
    protected = verify_runtime_parent_integrity(ROOT)
    return {
        "version": VERSION,
        "parent_integrity": "PASS",
        "protected_file_count": len(protected),
        "audit_chain_ok": store.verify_chain(),
        "execution_unlocked": False,
        "final_holdout_accessed": False,
    }


def connected_status(store: AuditStore, gateway: MT5Gateway, cfg: Dict[str, Any]) -> Dict[str, Any]:
    protected = verify_runtime_parent_integrity(ROOT)
    account = gateway.account_snapshot()
    symbol = gateway.symbol_snapshot()
    exposure = gateway.exposure_snapshot()
    return {
        "version": VERSION,
        "parent_integrity": "PASS",
        "protected_file_count": len(protected),
        "audit_chain_ok": store.verify_chain(),
        "execution_unlocked": demo_execution_enabled(cfg),
        "account": account.__dict__,
        "symbol": symbol.__dict__,
        "exposure": exposure.__dict__,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="XAU V16 R7-R1 hardened operational runtime")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--offline-status", action="store_true")
    group.add_argument("--status", action="store_true")
    group.add_argument("--recover", action="store_true")
    group.add_argument("--preflight-intent", type=Path)
    group.add_argument("--submit-intent", type=Path)
    args = parser.parse_args()

    cfg = load_config()
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    with SingleInstanceLock(LOCK_PATH):
        store = AuditStore(DB_PATH)
        gateway = None
        try:
            verify_runtime_parent_integrity(ROOT)
            if args.offline_status:
                print(json.dumps(offline_status(store), indent=2, sort_keys=True))
                return

            gateway = MT5Gateway(
                max_tick_age_seconds=cfg["max_tick_age_seconds"],
                max_spread_usd=cfg["max_spread_usd"],
            )
            gateway.connect()

            if args.status:
                print(json.dumps(connected_status(store, gateway, cfg), indent=2, sort_keys=True))
                return

            engine = ExecutionEngine(store, gateway, execution_enabled=demo_execution_enabled(cfg))
            if args.recover:
                result = engine.recover_inflight()
                print(json.dumps({"recovered": result}, indent=2, sort_keys=True))
                return

            if args.preflight_intent:
                intent = load_intent(args.preflight_intent)
                dry_engine = ExecutionEngine(store, gateway, execution_enabled=False)
                print(json.dumps(dry_engine.submit(intent), indent=2, sort_keys=True))
                return

            if args.submit_intent:
                if not demo_execution_enabled(cfg):
                    raise RuntimeError(
                        "DEMO_EXECUTION_LOCKED: set request_demo_execution=true and exact environment unlock; live accounts remain prohibited"
                    )
                intent = load_intent(args.submit_intent)
                print(json.dumps(engine.submit(intent), indent=2, sort_keys=True))
                return
        finally:
            if gateway is not None:
                gateway.shutdown()
            store.close()


if __name__ == "__main__":
    main()
