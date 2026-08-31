from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from r7_runtime.audit_store import AuditStore, StoreError
from r7_runtime.execution import ExecutionEngine
from r7_runtime.models import AccountSnapshot, BrokerMatch, ExposureSnapshot, OrderIntent, SymbolSnapshot


class FakeResult:
    order = 123456
    deal = 0


class FakeGateway:
    def __init__(self):
        self.loss = 5.0
        self.equity = 1000.0
        self.exposure = ExposureSnapshot(0, 0, 0.0, 0.0)
        self.post_send_exposure = ExposureSnapshot(1, 0, 0.01, 0.0)
        self.match = BrokerMatch(True, "POSITION", 123456, "OPEN")
        self.send_calls = 0
        self.preflight_calls = 0
        self.block_on_second = False

    def account_snapshot(self):
        return AccountSnapshot(1, "BlueberryMarkets-Demo", "SGD", self.equity, self.equity, self.equity)

    def symbol_snapshot(self):
        return SymbolSnapshot("XAUUSD.i", 3000.0, 3000.2, 1.0, 0.1, 0.01, 0.01, 100.0, 0.01, 0)

    def exposure_snapshot(self):
        self.preflight_calls += 1
        if self.send_calls > 0:
            return self.post_send_exposure
        if self.block_on_second and self.preflight_calls >= 2:
            return ExposureSnapshot(1, 0, 0.01, 0.0)
        return self.exposure

    def current_market_entry(self, side, symbol):
        return symbol.ask if side.upper() == "BUY" else symbol.bid

    def validate_broker_geometry(self, intent, symbol, entry):
        if intent.lot < symbol.volume_min or intent.lot > symbol.volume_max:
            raise RuntimeError("BROKER_VOLUME_RANGE_REJECT")
        if intent.side.upper() == "BUY" and intent.stop_price >= entry:
            raise RuntimeError("BUY_STOP_NOT_BELOW_ENTRY")
        if intent.side.upper() == "SELL" and intent.stop_price <= entry:
            raise RuntimeError("SELL_STOP_NOT_ABOVE_ENTRY")

    def projected_stop_loss_sgd(self, intent, entry):
        return self.loss

    def build_market_request(self, intent, entry):
        return {"price": entry, "symbol": "XAUUSD.i", "volume": intent.lot}

    def order_check(self, request):
        return True

    def order_send(self, request):
        self.send_calls += 1
        return FakeResult()

    def find_intent_at_broker(self, intent_id):
        return self.match


def intent(intent_id="abc", loss_source="BASE", lot=0.01):
    return OrderIntent(intent_id, "BUY", lot, 2999.0, 3002.0, loss_source)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = AuditStore(Path(self.tmp.name) / "state.sqlite3")
        self.gateway = FakeGateway()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_dry_run_never_sends(self):
        engine = ExecutionEngine(self.store, self.gateway, execution_enabled=False)
        result = engine.submit(intent())
        self.assertEqual(result["state"], "DRY_RUN_COMPLETE")
        self.assertEqual(self.gateway.send_calls, 0)

    def test_exact_operating_cap_is_allowed(self):
        self.gateway.loss = 5.5
        engine = ExecutionEngine(self.store, self.gateway, execution_enabled=False)
        result = engine.submit(intent())
        self.assertEqual(result["state"], "DRY_RUN_COMPLETE")

    def test_operating_cap_blocks(self):
        self.gateway.loss = 5.5001
        engine = ExecutionEngine(self.store, self.gateway, execution_enabled=False)
        result = engine.submit(intent())
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "OPERATING_RISK_CAP_BREACH")

    def test_constitutional_cap_blocks(self):
        self.gateway.loss = 6.1
        engine = ExecutionEngine(self.store, self.gateway, execution_enabled=False)
        result = engine.submit(intent())
        self.assertEqual(result["reason"], "CONSTITUTIONAL_RISK_CEILING_BREACH")

    def test_projected_equity_floor_blocks(self):
        self.gateway.equity = 850.1
        self.gateway.loss = 0.2
        engine = ExecutionEngine(self.store, self.gateway, execution_enabled=False)
        result = engine.submit(intent())
        self.assertEqual(result["reason"], "PROJECTED_EQUITY_FLOOR_BREACH")

    def test_max_lot_blocks_003(self):
        self.gateway.loss = 1.0
        engine = ExecutionEngine(self.store, self.gateway, execution_enabled=False)
        result = engine.submit(intent(lot=0.03))
        self.assertEqual(result["reason"], "MAX_CANONICAL_EXPOSURE_EXCEEDED")

    def test_retired_source_blocks(self):
        engine = ExecutionEngine(self.store, self.gateway, execution_enabled=False)
        result = engine.submit(intent(loss_source="AUX_RF_LTM"))
        self.assertEqual(result["reason"], "RETIRED_SOURCE_AUX_RF_LTM")

    def test_existing_position_blocks(self):
        self.gateway.exposure = ExposureSnapshot(1, 0, 0.01, 0.0)
        engine = ExecutionEngine(self.store, self.gateway, execution_enabled=False)
        result = engine.submit(intent())
        self.assertEqual(result["reason"], "EXISTING_XAU_EXPOSURE_BLOCK")

    def test_existing_pending_order_blocks(self):
        self.gateway.exposure = ExposureSnapshot(0, 1, 0.0, 0.01)
        engine = ExecutionEngine(self.store, self.gateway, execution_enabled=False)
        result = engine.submit(intent())
        self.assertEqual(result["reason"], "EXISTING_XAU_EXPOSURE_BLOCK")

    def test_duplicate_submit_is_suppressed(self):
        engine = ExecutionEngine(self.store, self.gateway, execution_enabled=False)
        first = engine.submit(intent("same"))
        second = engine.submit(intent("same"))
        self.assertEqual(first["state"], "DRY_RUN_COMPLETE")
        self.assertTrue(second["duplicate_suppressed"])
        self.assertEqual(self.gateway.send_calls, 0)

    def test_idempotency_collision_fails(self):
        self.store.reserve_intent("same", intent("same").canonical_payload())
        changed = intent("same", lot=0.02).canonical_payload()
        with self.assertRaises(StoreError):
            self.store.reserve_intent("same", changed)

    def test_second_preflight_exposure_change_prevents_send(self):
        self.gateway.block_on_second = True
        engine = ExecutionEngine(self.store, self.gateway, execution_enabled=True)
        result = engine.submit(intent())
        self.assertEqual(result["state"], "ABANDONED_BEFORE_SEND")
        self.assertEqual(self.gateway.send_calls, 0)

    def test_successful_send_is_reconciled(self):
        engine = ExecutionEngine(self.store, self.gateway, execution_enabled=True)
        result = engine.submit(intent())
        self.assertEqual(result["state"], "ACKNOWLEDGED")
        self.assertEqual(self.gateway.send_calls, 1)
        self.assertTrue(result["post_send"]["ok"])

    def test_post_send_exposure_count_violation_forces_manual_review(self):
        self.gateway.post_send_exposure = ExposureSnapshot(2, 0, 0.02, 0.0)
        engine = ExecutionEngine(self.store, self.gateway, execution_enabled=True)
        result = engine.submit(intent())
        self.assertEqual(self.gateway.send_calls, 1)
        self.assertEqual(result["state"], "MANUAL_REVIEW_NO_RESUBMIT")
        self.assertEqual(result["reason"], "POST_SEND_EXPOSURE_COUNT_MISMATCH")

    def test_post_send_volume_violation_forces_manual_review(self):
        self.gateway.post_send_exposure = ExposureSnapshot(1, 0, 0.03, 0.0)
        engine = ExecutionEngine(self.store, self.gateway, execution_enabled=True)
        result = engine.submit(intent())
        self.assertEqual(result["state"], "MANUAL_REVIEW_NO_RESUBMIT")
        self.assertEqual(result["reason"], "POST_SEND_MAX_EXPOSURE_BREACH")

    def test_restart_never_resubmits_ambiguous_send(self):
        payload = intent("crash").canonical_payload()
        self.store.reserve_intent("crash", payload)
        self.store.transition("crash", "PREFLIGHT_OK")
        self.store.transition("crash", "SUBMITTING")
        self.gateway.match = BrokerMatch(False)
        engine = ExecutionEngine(self.store, self.gateway, execution_enabled=True)
        recovered = engine.recover_inflight()
        self.assertEqual(recovered[0]["state"], "MANUAL_REVIEW_NO_RESUBMIT")
        self.assertEqual(self.gateway.send_calls, 0)

    def test_restart_reconciles_existing_broker_position_without_resend(self):
        payload = intent("recover").canonical_payload()
        self.store.reserve_intent("recover", payload)
        self.store.transition("recover", "PREFLIGHT_OK")
        self.store.transition("recover", "SUBMITTING")
        self.gateway.post_send_exposure = ExposureSnapshot(1, 0, 0.01, 0.0)
        # Simulate an already-existing broker position without calling order_send now.
        self.gateway.send_calls = 1
        engine = ExecutionEngine(self.store, self.gateway, execution_enabled=True)
        recovered = engine.recover_inflight()
        self.assertEqual(recovered[0]["state"], "ACKNOWLEDGED")
        self.assertEqual(self.gateway.send_calls, 1)

    def test_audit_chain_verifies(self):
        self.store.append_event("A", {"x": 1})
        self.store.append_event("B", {"y": 2})
        self.assertTrue(self.store.verify_chain())


if __name__ == "__main__":
    unittest.main()
