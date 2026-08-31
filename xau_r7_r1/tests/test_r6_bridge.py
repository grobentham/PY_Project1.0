from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from r7_runtime.audit_store import AuditStore
from r7_runtime.constants import CANONICAL_R6_ZIP_SHA256
from r7_runtime.models import AccountSnapshot, BrokerMatch, ExposureSnapshot, SymbolSnapshot
from r7_runtime.r6_bridge import R6InboxProcessor


NOW = 1_800_000_000_000


def payload(decision_id="bridge-1", **updates):
    d = {
        "schema": "V16_R6_ADMITTED_DECISION_V1", "policy": "FROZEN_V16_R6",
        "parent_zip_sha256": CANONICAL_R6_ZIP_SHA256, "decision_id": decision_id,
        "signal_bar_ms": NOW - 1000, "emitted_at_ms": NOW - 500, "side": 1,
        "source": "TIME_LANE", "priority": 1,
        "family": "LIQUIDITY_TRANSITION_MOMENTUM", "signal_type": "",
        "atr_usd": 2.0, "stop_atr": 1.2, "target_atr": 2.4,
        "geometry_used": "PRIMARY_1P2_2P4", "lot_size": 0.01, "admitted": True,
    }
    d.update(updates)
    return d


class FakeResult:
    order = 123
    deal = 0


class Gateway:
    def __init__(self):
        self.send_calls = 0
        self.after_match = BrokerMatch(True, "POSITION", 123, "OPEN")
        self.after_exposure = ExposureSnapshot(1, 0, 0.01, 0.0)

    def account_snapshot(self):
        return AccountSnapshot(1, "BlueberryMarkets-Demo", "SGD", 1000.0, 1000.0, 1000.0)

    def symbol_snapshot(self):
        return SymbolSnapshot("XAUUSD.i", 3000.0, 3000.2, 1.0, 0.1, 0.01, 0.01, 100.0, 0.01, 0)

    def exposure_snapshot(self):
        return self.after_exposure if self.send_calls else ExposureSnapshot(0, 0, 0.0, 0.0)

    def current_market_entry(self, side, symbol):
        return symbol.ask if side.upper() == "BUY" else symbol.bid

    def validate_broker_geometry(self, intent, symbol, entry):
        if intent.side == "BUY" and intent.stop_price >= entry:
            raise RuntimeError("BAD_STOP")

    def projected_stop_loss_sgd(self, intent, entry):
        return 5.0

    def build_market_request(self, intent, entry):
        return {"price": entry, "sl": intent.stop_price, "tp": intent.take_profit_price, "volume": intent.lot}

    def order_check(self, request):
        return True

    def order_send(self, request):
        self.send_calls += 1
        return FakeResult()

    def find_intent_at_broker(self, intent_id):
        return self.after_match if self.send_calls else BrokerMatch(False)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = AuditStore(self.root / "state.sqlite3")
        self.gateway = Gateway()
        self.bridge = R6InboxProcessor(self.root / "bridge", self.store, self.gateway, execution_enabled=False)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def put(self, name, obj):
        p = self.bridge.inbox / name
        if isinstance(obj, bytes):
            p.write_bytes(obj)
        else:
            p.write_text(json.dumps(obj), encoding="utf-8")
        return p

    def test_valid_decision_dry_run_is_archived_processed(self):
        p = self.put("a.json", payload())
        result = self.bridge.process_path(p, now_ms=NOW)
        self.assertEqual(result["state"], "DRY_RUN_COMPLETE")
        self.assertFalse(p.exists())
        self.assertTrue(Path(result["archived_to"]).parent.name == "processed")
        self.assertEqual(self.gateway.send_calls, 0)

    def test_bad_json_is_quarantined_without_broker_send(self):
        p = self.put("bad.json", b"{not-json")
        result = self.bridge.process_path(p, now_ms=NOW)
        self.assertEqual(result["state"], "REJECTED_DECISION")
        self.assertEqual(Path(result["archived_to"]).parent.name, "rejected")
        self.assertEqual(self.gateway.send_calls, 0)

    def test_duplicate_same_decision_is_suppressed(self):
        first = self.put("one.json", payload("same"))
        self.bridge.process_path(first, now_ms=NOW)
        second = self.put("two.json", payload("same"))
        result = self.bridge.process_path(second, now_ms=NOW)
        self.assertEqual(result["state"], "DUPLICATE_SUPPRESSED")
        self.assertEqual(self.gateway.send_calls, 0)

    def test_same_id_changed_frozen_payload_causes_manual_review_not_send(self):
        first = self.put("one.json", payload("collision"))
        self.bridge.process_path(first, now_ms=NOW)
        second = self.put("two.json", payload("collision", atr_usd=2.1))
        result = self.bridge.process_path(second, now_ms=NOW)
        self.assertEqual(result["state"], "MANUAL_REVIEW_NO_RESUBMIT")
        self.assertTrue(self.bridge.pause_marker.exists())
        self.assertEqual(self.gateway.send_calls, 0)

    def test_ambiguous_send_pauses_inbox_and_never_auto_resubmits(self):
        self.store.close()
        self.store = AuditStore(self.root / "state2.sqlite3")
        self.gateway.after_match = BrokerMatch(False)
        self.bridge = R6InboxProcessor(self.root / "bridge2", self.store, self.gateway, execution_enabled=True)
        p = self.put("send.json", payload("ambiguous"))
        result = self.bridge.process_path(p, now_ms=NOW)
        self.assertEqual(result["state"], "MANUAL_REVIEW_NO_RESUBMIT")
        self.assertEqual(self.gateway.send_calls, 1)
        self.assertTrue(self.bridge.pause_marker.exists())
        later = self.put("later.json", payload("later"))
        with self.assertRaisesRegex(Exception, "PAUSED"):
            self.bridge.process_path(later, now_ms=NOW)
        self.assertEqual(self.gateway.send_calls, 1)

    def test_drain_stops_after_manual_review(self):
        self.store.close()
        self.store = AuditStore(self.root / "state3.sqlite3")
        self.gateway.after_match = BrokerMatch(False)
        self.bridge = R6InboxProcessor(self.root / "bridge3", self.store, self.gateway, execution_enabled=True)
        self.put("01.json", payload("ambiguous-drain"))
        self.put("02.json", payload("must-not-send"))
        results = self.bridge.drain_once(now_ms=NOW)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["state"], "MANUAL_REVIEW_NO_RESUBMIT")
        self.assertTrue((self.bridge.inbox / "02.json").exists())
        self.assertEqual(self.gateway.send_calls, 1)


if __name__ == "__main__":
    unittest.main()
