from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Dict

from .audit_store import AuditStore
from .constants import (
    CAUSAL_R6_PRODUCER_READY,
    EXECUTION_UNLOCK_ENV,
    EXECUTION_UNLOCK_VALUE,
    HARD_MAX_SPREAD_USD,
    HARD_MAX_TICK_AGE_SECONDS,
    R6_BRIDGE_PAUSE_STATE_KEY,
    VERSION,
)
from .execution import ExecutionEngine
from .instance_lock import SingleInstanceLock
from .models import OrderIntent
from .mt5_gateway import MT5Gateway
from .r6_admission_authority import producer_admission_status
from .r6_bridge import R6InboxProcessor
from .r6_integrity import verify_runtime_package_integrity

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "r7_runtime_state"
DB_PATH = RUNTIME_DIR / "r7_r1_state.sqlite3"
LOCK_PATH = RUNTIME_DIR / "r7_r1_runtime.lock"
BRIDGE_ROOT = ROOT / "r7_r6_bridge"
CONFIG_PATH = ROOT / "R7_R1_RUNTIME_CONFIG.json"
_ALLOWED_CONFIG_KEYS = {"max_tick_age_seconds", "max_spread_usd", "request_demo_execution", "_note"}


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


def producer_execution_admitted() -> bool:
    """Require readiness plus V5 canonical-reference admission authority."""
    if not CAUSAL_R6_PRODUCER_READY:
        return False
    status = producer_admission_status(ROOT)
    return bool(
        status.get("ready", False)
        and status.get("canonical_reference_replay_pass", False)
        and status.get("authority_version") == "R7_R1_R6_PRODUCER_ADMISSION_AUTHORITY_V5"
        and status.get("final_holdout_accessed") is False
        and status.get("strategy_retuned") is False
    )


def demo_execution_enabled(cfg: Dict[str, Any]) -> bool:
    return (
        producer_execution_admitted()
        and bool(cfg["request_demo_execution"])
        and os.environ.get(EXECUTION_UNLOCK_ENV) == EXECUTION_UNLOCK_VALUE
    )


def load_intent(path: Path) -> OrderIntent:
    """Load an absolute intent for diagnostic preflight only. It has no send authority."""
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
    target = None if raw.get("take_profit_price") is None else _finite_number(raw["take_profit_price"], "INTENT_TAKE_PROFIT_PRICE")
    return OrderIntent(raw["client_intent_id"], raw["side"], lot, stop, target, raw["source"])


def diagnostic_preflight(gateway, intent: OrderIntent) -> Dict[str, Any]:
    """Run raw diagnostic preflight without touching the operational intent ledger."""
    with tempfile.TemporaryDirectory(prefix="xau_r7_r1_diag_") as td:
        diag_store = AuditStore(Path(td) / "diagnostic.sqlite3")
        try:
            result = ExecutionEngine(diag_store, gateway, execution_enabled=False).submit(intent)
            result["diagnostic_ephemeral_state"] = True
            result["operational_ledger_touched"] = False
            return result
        finally:
            diag_store.close()


def _bridge_paused(store: AuditStore) -> bool:
    return bool(store.get_runtime_state(R6_BRIDGE_PAUSE_STATE_KEY, False)) or (BRIDGE_ROOT / "PAUSED_MANUAL_REVIEW").exists()


def offline_status(store: AuditStore, package_integrity: Dict[str, Any], store_integrity: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    admission = producer_admission_status(ROOT)
    return {
        "version": VERSION,
        "package_integrity": "PASS",
        "integrity": package_integrity,
        "state_integrity": store_integrity,
        "demo_execution_requested": cfg["request_demo_execution"],
        "causal_r6_producer_ready": bool(CAUSAL_R6_PRODUCER_READY),
        "producer_admission_ready": bool(admission.get("ready", False)),
        "producer_admission_authority_version": admission.get("authority_version"),
        "canonical_reference_replay_pass": bool(admission.get("canonical_reference_replay_pass", False)),
        "execution_unlocked": demo_execution_enabled(cfg),
        "raw_intent_send_authority": False,
        "diagnostic_preflight_uses_operational_ledger": False,
        "r6_bridge_root": str(BRIDGE_ROOT),
        "r6_bridge_paused": _bridge_paused(store),
        "final_holdout_accessed": False,
    }


def connected_status(store: AuditStore, gateway: MT5Gateway, cfg: Dict[str, Any], package_integrity: Dict[str, Any], store_integrity: Dict[str, Any]) -> Dict[str, Any]:
    admission = producer_admission_status(ROOT)
    return {
        "version": VERSION,
        "package_integrity": "PASS",
        "integrity": package_integrity,
        "state_integrity": store_integrity,
        "demo_execution_requested": cfg["request_demo_execution"],
        "causal_r6_producer_ready": bool(CAUSAL_R6_PRODUCER_READY),
        "producer_admission_ready": bool(admission.get("ready", False)),
        "producer_admission_authority_version": admission.get("authority_version"),
        "canonical_reference_replay_pass": bool(admission.get("canonical_reference_replay_pass", False)),
        "execution_unlocked": demo_execution_enabled(cfg),
        "raw_intent_send_authority": False,
        "diagnostic_preflight_uses_operational_ledger": False,
        "account": gateway.account_snapshot().__dict__,
        "symbol": gateway.symbol_snapshot().__dict__,
        "exposure": gateway.exposure_snapshot().__dict__,
        "r6_bridge_root": str(BRIDGE_ROOT),
        "r6_bridge_paused": _bridge_paused(store),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="XAU V16 R7-R1 hardened operational runtime")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--offline-status", action="store_true")
    group.add_argument("--status", action="store_true")
    group.add_argument("--recover", action="store_true")
    group.add_argument("--preflight-intent", type=Path, help="diagnostic only; never grants order-send authority")
    group.add_argument("--process-r6-decision", type=Path)
    group.add_argument("--drain-r6-inbox", action="store_true")
    group.add_argument("--run-r6-inbox", action="store_true")
    group.add_argument("--clear-r6-pause", action="store_true")
    parser.add_argument("--resume-ack", default="")
    args = parser.parse_args()

    cfg = load_config()
    package_integrity = verify_runtime_package_integrity(ROOT)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with SingleInstanceLock(LOCK_PATH):
        store = AuditStore(DB_PATH)
        gateway = None
        try:
            store_integrity = store.verify_store_integrity()
            if args.offline_status:
                print(json.dumps(offline_status(store, package_integrity, store_integrity, cfg), indent=2, sort_keys=True))
                return

            gateway = MT5Gateway(max_tick_age_seconds=cfg["max_tick_age_seconds"], max_spread_usd=cfg["max_spread_usd"])
            gateway.connect()
            if args.status:
                print(json.dumps(connected_status(store, gateway, cfg, package_integrity, store_integrity), indent=2, sort_keys=True))
                return

            execution_enabled = demo_execution_enabled(cfg)
            engine = ExecutionEngine(store, gateway, execution_enabled=execution_enabled)
            if args.recover:
                print(json.dumps({"recovered": engine.recover_inflight()}, indent=2, sort_keys=True))
                return
            if args.preflight_intent:
                print(json.dumps(diagnostic_preflight(gateway, load_intent(args.preflight_intent)), indent=2, sort_keys=True))
                return

            bridge = R6InboxProcessor(BRIDGE_ROOT, store, gateway, execution_enabled=execution_enabled)
            if args.clear_r6_pause:
                print(json.dumps(bridge.clear_pause(args.resume_ack), indent=2, sort_keys=True))
                return
            if args.process_r6_decision or args.drain_r6_inbox or args.run_r6_inbox:
                if not CAUSAL_R6_PRODUCER_READY:
                    raise RuntimeError("CAUSAL_R6_PRODUCER_NOT_ADMITTED: automatic decision execution remains hard-locked")
                if not producer_execution_admitted():
                    raise RuntimeError("CAUSAL_R6_PRODUCER_V5_AUTHORITY_NOT_ADMITTED: canonical-reference replay authority is required")
                if not execution_enabled:
                    raise RuntimeError("R6_INBOX_DEMO_EXECUTION_LOCKED: automatic decision consumption is disabled until all producer and demo unlock gates pass")
            if args.process_r6_decision:
                print(json.dumps(bridge.process_path(args.process_r6_decision), indent=2, sort_keys=True))
                return
            if args.drain_r6_inbox:
                print(json.dumps({"results": bridge.drain_once()}, indent=2, sort_keys=True))
                return
            if args.run_r6_inbox:
                bridge.run_forever()
                return
        finally:
            if gateway is not None:
                gateway.shutdown()
            store.close()


if __name__ == "__main__":
    main()
