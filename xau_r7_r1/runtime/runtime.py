from __future__ import annotations

import argparse
import json
import math
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
from .r6_integrity import verify_runtime_package_integrity


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "r7_runtime_state"
DB_PATH = RUNTIME_DIR / "r7_r1_state.sqlite3"
LOCK_PATH = RUNTIME_DIR / "r7_r1_runtime.lock"
CONFIG_PATH = ROOT / "R7_R1_RUNTIME_CONFIG.json"
_ALLOWED_CONFIG_KEYS = {
    "max_tick_age_seconds",
    "max_spread_usd",
    "request_demo_execution",
    "_note",
}


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise RuntimeError(f"{name}_MUST_BE_NUMERIC_NOT_BOOLEAN")
    try:
        result = float(value)
    except Exception as exc:
        raise RuntimeError(f"{name}_INVALID_NUMERIC_VALUE") from exc
    if not math.isfinite(result):
        raise RuntimeError(f"{name}_NONFINITE")
    return result


def load_config() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "max_tick_age_seconds": HARD_MAX_TICK_AGE_SECONDS,
        "max_spread_usd": HARD_MAX_SPREAD_USD,
        "request_demo_execution": False,
    }
    if CONFIG_PATH.exists():
        user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(user, dict):
            raise RuntimeError("R7_R1_CONFIG_INVALID")
        unknown = set(user) - _ALLOWED_CONFIG_KEYS
        if unknown:
            raise RuntimeError("R7_R1_CONFIG_UNKNOWN_KEYS:" + ",".join(sorted(unknown)))
        cfg.update(user)
    tick_age = _finite_number(cfg["max_tick_age_seconds"], "CONFIG_TICK_AGE")
    spread = _finite_number(cfg["max_spread_usd"], "CONFIG_SPREAD")
    if tick_age <= 0 or tick_age > HARD_MAX_TICK_AGE_SECONDS:
        raise RuntimeError("CONFIG_TICK_AGE_MAY_NOT_WEAKEN_HARD_GUARD")
    if spread <= 0 or spread > HARD_MAX_SPREAD_USD:
        raise RuntimeError("CONFIG_SPREAD_MAY_NOT_WEAKEN_HARD_GUARD")
    requested = cfg.get("request_demo_execution", False)
    if not isinstance(requested, bool):
        raise RuntimeError("CONFIG_REQUEST_DEMO_EXECUTION_MUST_BE_BOOLEAN")
    cfg["max_tick_age_seconds"] = tick_age
    cfg["max_spread_usd"] = spread
    cfg["request_demo_execution"] = requested
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
    for key in ("client_intent_id", "side", "source"):
        if not isinstance(raw[key], str):
            raise RuntimeError(f"INTENT_{key.upper()}_MUST_BE_STRING")
    lot = _finite_number(raw["lot"], "INTENT_LOT")
    stop = _finite_number(raw["stop_price"], "INTENT_STOP_PRICE")
    target = None
    if raw.get("take_profit_price") is not None:
        target = _finite_number(raw["take_profit_price"], "INTENT_TAKE_PROFIT_PRICE")
    return OrderIntent(
        client_intent_id=raw["client_intent_id"],
        side=raw["side"],
        lot=lot,
        stop_price=stop,
        take_profit_price=target,
        source=raw["source"],
    )


def offline_status(store: AuditStore, integrity: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "version": VERSION,
        "package_integrity": "PASS",
        "integrity": integrity,
        "audit_chain_ok": store.verify_chain(),
        "demo_execution_requested": cfg["request_demo_execution"],
        "execution_unlocked": demo_execution_enabled(cfg),
        "final_holdout_accessed": False,
    }


def connected_status(store: AuditStore, gateway: MT5Gateway, cfg: Dict[str, Any], integrity: Dict[str, Any]) -> Dict[str, Any]:
    account = gateway.account_snapshot()
    symbol = gateway.symbol_snapshot()
    exposure = gateway.exposure_snapshot()
    return {
        "version": VERSION,
        "package_integrity": "PASS",
        "integrity": integrity,
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
    # Verify immutable parent + R7 runtime code before creating lock/database state.
    integrity = verify_runtime_package_integrity(ROOT)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    with SingleInstanceLock(LOCK_PATH):
        store = AuditStore(DB_PATH)
        gateway = None
        try:
            if args.offline_status:
                print(json.dumps(offline_status(store, integrity, cfg), indent=2, sort_keys=True))
                return

            gateway = MT5Gateway(
                max_tick_age_seconds=cfg["max_tick_age_seconds"],
                max_spread_usd=cfg["max_spread_usd"],
            )
            gateway.connect()

            if args.status:
                print(json.dumps(connected_status(store, gateway, cfg, integrity), indent=2, sort_keys=True))
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
