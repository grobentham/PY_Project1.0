from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from r7_runtime.audit_store import AuditStore, StoreError
from r7_runtime.constants import R6_EXECUTION_AUTHORITY
from r7_runtime.execution import ExecutionEngine
from r7_runtime.models import AccountSnapshot, BrokerMatch, ExposureSnapshot, OrderIntent, OwnedPositionSnapshot, SymbolSnapshot


class FakeResult:
    order = 123456
    deal = 0
    retcode = 10009
    volume = 0.01
    price = 3000.2


class FakeGateway:
    def __init__(self):
        self.loss = 5.0
        self.actual_stop_loss = 5.0
        self.remaining_stop_loss = 5.0
        self.equity = 1000.0
        self.exposure = ExposureSnapshot(0, 0, 0.0, 0.0)
        self.post_send_exposure = ExposureSnapshot(1, 0, 0.01, 0.0)
        self.match_before_send = BrokerMatch(False)
        self.match_after_send = BrokerMatch(True, "POSITION", 123456, "OPEN")
        self.recovery_match = None
        self.broker_lookup_error = False
        self.send_calls = 0
        self.send_state = "DONE"
        self.preflight_calls = 0
        self.block_on_second = False
        self.owned_position_snapshot = OwnedPositionSnapshot(
            123456, "XAUUSD.i", "BUY", 0.01, 3000.2, 2999.2, 3002.2, 1607101, "R7R1:r6_test"
        )
        self.owned_pending_orders = []
        self.containment_calls = 0
        self.containment_should_fail = False

    def account_snapshot(self):
        return AccountSnapshot(1, "BlueberryMarkets-Demo", "SGD", self.equity, self.equity, self.equity)

    def symbol_snapshot(self):
        return SymbolSnapshot("XAUUSD.i", 3000.0, 3000.2, 1.0, 0.1, 0.01, 0.01, 100.0, 0.01, 0)

    def exposure_snapshot(self):
        self.preflight_calls += 1
        if self.send_calls > 0 or (self.recovery_match is not None and self.recovery_match.found):
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
        return {"price": entry, "symbol": "XAUUSD.i", "volume": intent.lot, "sl": intent.stop_price, "tp": intent.take_profit_price}

    def order_check(self, request):
        return True

    def order_send(self, request):
        self.send_calls += 1
        return FakeResult()

    def order_send_state(self, result):
        return self.send_state

    def find_intent_at_broker(self, intent_id):
        if self.broker_lookup_error:
            raise RuntimeError("BROKER_QUERY_FAILED")
        if self.recovery_match is not None:
            return self.recovery_match
        if self.send_calls > 0:
            return self.match_after_send
        return self.match_before_send

    def owned_orders(self, intent_id):
        return list(self.owned_pending_orders)

    def owned_position(self, intent_id):
        has_position_match = (
            (self.recovery_match is not None and self.recovery_match.found and self.recovery_match.kind == "POSITION")
            or (self.send_calls > 0 and self.match_after_send.kind == "POSITION")
            or (self.match_before_send.found and self.match_before_send.kind == "POSITION")
        )
        return self.owned_position_snapshot if has_position_match else None

    def position_stop_loss_sgd(self, position):
        return self.actual_stop_loss

    def position_remaining_stop_loss_sgd(self, position):
        return self.remaining_stop_loss

    def emergency_flatten_owned_intent(self, intent_id):
        self.containment_calls += 1
        if self.containment_should_fail:
            raise RuntimeError("CONTAINMENT_FAILED")
        self.owned_pending_orders = []
        self.owned_position_snapshot = None
        self.post_send_exposure = ExposureSnapshot(0, 0, 0.0, 0.0)
        return {
            "ok": True,
            "cancelled_orders": [],
            "close_attempted_positions": [123456],
            "remaining_owned_positions": [],
            "remaining_owned_orders": [],
        }


def intent(intent_id="abc", loss_source="TIME_LANE", lot=0.01, *, authorized=True):
    if authorized:
        return OrderIntent(
            intent_id, "BUY", lot, 2999.2, 3002.2, loss_source,
            frozen_atr_usd=1.0,
            frozen_stop_atr=1.0,
            frozen_target_atr=2.0,
            decision_fingerprint="a" * 64,
            execution_authority=R6_EXECUTION_AUTHORITY,
        )
    return OrderIntent(intent_id, "BUY", lot, 2999.0, 3002.0, loss_source)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = AuditStore(Path(self.tmp.name) / "state.sqlite3")
        self.gateway = FakeGateway()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_raw_intent_cannot_send_even_when_execution_enabled(self):
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=True).submit(intent("raw", authorized=False))
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "FROZEN_R6_EXECUTION_AUTHORITY_REQUIRED")
        self.assertEqual(self.gateway.send_calls, 0)

    def test_dry_run_raw_intent_is_diagnostic_only_and_never_sends(self):
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=False).submit(intent("dryraw", authorized=False))
        self.assertEqual(result["state"], "DRY_RUN_COMPLETE")
        self.assertEqual(self.gateway.send_calls, 0)

    def test_exact_operating_cap_is_allowed(self):
        self.gateway.loss = 5.5
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=False).submit(intent())
        self.assertEqual(result["state"], "DRY_RUN_COMPLETE")

    def test_operating_cap_blocks(self):
        self.gateway.loss = 5.5001
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=False).submit(intent())
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "OPERATING_RISK_CAP_BREACH")

    def test_constitutional_cap_blocks(self):
        self.gateway.loss = 6.1
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=False).submit(intent())
        self.assertEqual(result["reason"], "CONSTITUTIONAL_RISK_CEILING_BREACH")

    def test_projected_equity_floor_blocks(self):
        self.gateway.equity = 850.1
        self.gateway.loss = 0.2
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=False).submit(intent())
        self.assertEqual(result["reason"], "PROJECTED_EQUITY_FLOOR_BREACH")

    def test_max_lot_blocks_003(self):
        self.gateway.loss = 1.0
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=False).submit(intent(lot=0.03))
        self.assertEqual(result["reason"], "MAX_CANONICAL_EXPOSURE_EXCEEDED")

    def test_retired_source_blocks(self):
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=False).submit(intent(loss_source="AUX_RF_LTM"))
        self.assertEqual(result["reason"], "RETIRED_SOURCE_AUX_RF_LTM")

    def test_existing_position_blocks(self):
        self.gateway.exposure = ExposureSnapshot(1, 0, 0.01, 0.0)
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=False).submit(intent())
        self.assertEqual(result["reason"], "EXISTING_XAU_EXPOSURE_BLOCK")

    def test_existing_pending_order_blocks(self):
        self.gateway.exposure = ExposureSnapshot(0, 1, 0.0, 0.01)
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=False).submit(intent())
        self.assertEqual(result["reason"], "EXISTING_XAU_EXPOSURE_BLOCK")

    def test_duplicate_submit_is_suppressed_locally(self):
        engine = ExecutionEngine(self.store, self.gateway, execution_enabled=False)
        first = engine.submit(intent("same"))
        second = engine.submit(intent("same"))
        self.assertEqual(first["state"], "DRY_RUN_COMPLETE")
        self.assertTrue(second["duplicate_suppressed"])
        self.assertEqual(self.gateway.send_calls, 0)

    def test_broker_side_historical_duplicate_is_acknowledged_without_send(self):
        self.gateway.match_before_send = BrokerMatch(True, "DEAL", 991, "HISTORICAL")
        self.gateway.post_send_exposure = ExposureSnapshot(0, 0, 0.0, 0.0)
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=True).submit(intent("brokerdup"))
        self.assertEqual(result["state"], "ACKNOWLEDGED")
        self.assertEqual(self.gateway.send_calls, 0)

    def test_broker_duplicate_query_failure_fails_safe(self):
        self.gateway.broker_lookup_error = True
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=True).submit(intent("lookuperr"))
        self.assertEqual(result["state"], "FAILED_SAFE")
        self.assertEqual(self.gateway.send_calls, 0)

    def test_idempotency_collision_fails_and_is_audited(self):
        self.store.reserve_intent("same", intent("same").canonical_payload())
        changed = intent("same", lot=0.02).canonical_payload()
        with self.assertRaises(StoreError):
            self.store.reserve_intent("same", changed)
        count = self.store.conn.execute("SELECT COUNT(*) FROM audit_events WHERE event_type='INTENT_IDEMPOTENCY_COLLISION'").fetchone()[0]
        self.assertEqual(count, 1)
        self.assertTrue(self.store.verify_chain())

    def test_second_preflight_exposure_change_prevents_send(self):
        self.gateway.block_on_second = True
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=True).submit(intent())
        self.assertEqual(result["state"], "ABANDONED_BEFORE_SEND")
        self.assertEqual(self.gateway.send_calls, 0)

    def test_frozen_geometry_is_rematerialized_on_preflight(self):
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=False).submit(intent("geom"))
        self.assertAlmostEqual(result["geometry"]["stop_price"], 2999.2)
        self.assertAlmostEqual(result["geometry"]["take_profit_price"], 3002.2)

    def test_successful_send_requires_safe_actual_fill(self):
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=True).submit(intent())
        self.assertEqual(result["state"], "ACKNOWLEDGED")
        self.assertEqual(self.gateway.send_calls, 1)
        self.assertEqual(self.gateway.containment_calls, 0)
        self.assertTrue(result["post_send"]["ok"])
        self.assertTrue(result["actual_fill_safety"]["ok"])
        self.assertTrue(result["actual_fill_safety"]["protection_match"]["ok"])
        self.assertEqual(result["actual_fill_safety"]["risk_basis"], "PRE_SEND_EQUITY_ACTUAL_FILL_TO_STOP")

    def test_done_partial_never_acknowledges_and_contains(self):
        self.gateway.send_state = "DONE_PARTIAL"
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=True).submit(intent("partialret"))
        self.assertEqual(result["state"], "MANUAL_REVIEW_NO_RESUBMIT")
        self.assertEqual(result["reason"], "NON_ATOMIC_ORDER_SEND_RESULT:DONE_PARTIAL")
        self.assertEqual(self.gateway.containment_calls, 1)

    def test_placed_never_acknowledges_and_contains(self):
        self.gateway.send_state = "PLACED"
        self.gateway.owned_pending_orders = [SimpleNamespace(ticket=7001)]
        self.gateway.post_send_exposure = ExposureSnapshot(0, 1, 0.0, 0.01)
        self.gateway.owned_position_snapshot = None
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=True).submit(intent("placed"))
        self.assertEqual(result["state"], "MANUAL_REVIEW_NO_RESUBMIT")
        self.assertEqual(result["reason"], "NON_ATOMIC_ORDER_SEND_RESULT:PLACED")
        self.assertEqual(self.gateway.containment_calls, 1)

    def test_immediate_deal_without_stable_position_is_not_acknowledged(self):
        self.gateway.match_after_send = BrokerMatch(True, "DEAL", 9001, "HISTORICAL")
        self.gateway.post_send_exposure = ExposureSnapshot(0, 0, 0.0, 0.0)
        self.gateway.owned_position_snapshot = None
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=True).submit(intent("dealonly"))
        self.assertEqual(result["state"], "MANUAL_REVIEW_NO_RESUBMIT")
        self.assertEqual(result["reason"], "POST_SEND_DEAL_WITHOUT_STABLE_POSITION")
        self.assertEqual(self.gateway.containment_calls, 1)

    def test_actual_fill_operating_risk_breach_is_contained(self):
        self.gateway.actual_stop_loss = 5.5001
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=True).submit(intent("fillrisk"))
        self.assertEqual(result["state"], "MANUAL_REVIEW_NO_RESUBMIT")
        self.assertEqual(result["reason"], "ACTUAL_FILL_UNSAFE:OPERATING_RISK_CAP_BREACH")
        self.assertEqual(self.gateway.containment_calls, 1)
        self.assertTrue(result["containment"]["ok"])

    def test_partial_fill_volume_mismatch_is_contained(self):
        self.gateway.post_send_exposure = ExposureSnapshot(1, 0, 0.005, 0.0)
        self.gateway.owned_position_snapshot = OwnedPositionSnapshot(
            123456, "XAUUSD.i", "BUY", 0.005, 3000.2, 2999.2, 3002.2, 1607101, "R7R1:r6_partial"
        )
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=True).submit(intent("partial"))
        self.assertEqual(result["state"], "MANUAL_REVIEW_NO_RESUBMIT")
        self.assertEqual(result["reason"], "ACTUAL_FILL_UNSAFE:ACTUAL_FILL_VOLUME_MISMATCH")
        self.assertEqual(self.gateway.containment_calls, 1)

    def test_pending_fill_remainder_is_contained(self):
        self.gateway.post_send_exposure = ExposureSnapshot(1, 1, 0.01, 0.01)
        self.gateway.owned_pending_orders = [SimpleNamespace(ticket=8001)]
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=True).submit(intent("remainder"))
        self.assertEqual(result["state"], "MANUAL_REVIEW_NO_RESUBMIT")
        self.assertEqual(result["reason"], "POST_SEND_EXPOSURE_COUNT_MISMATCH")
        self.assertEqual(self.gateway.containment_calls, 1)

    def test_market_request_left_pending_is_cancelled_not_acknowledged(self):
        self.gateway.match_after_send = BrokerMatch(True, "ORDER", 8002, "PENDING")
        self.gateway.post_send_exposure = ExposureSnapshot(0, 1, 0.0, 0.01)
        self.gateway.owned_position_snapshot = None
        self.gateway.owned_pending_orders = [SimpleNamespace(ticket=8002)]
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=True).submit(intent("pending"))
        self.assertEqual(result["state"], "MANUAL_REVIEW_NO_RESUBMIT")
        self.assertEqual(result["reason"], "POST_SEND_PENDING_ORDER_NOT_SAFE_TO_ACK")
        self.assertEqual(self.gateway.containment_calls, 1)

    def test_missing_stop_is_contained(self):
        self.gateway.owned_position_snapshot = OwnedPositionSnapshot(
            123456, "XAUUSD.i", "BUY", 0.01, 3000.2, 0.0, 3002.2, 1607101, "R7R1:r6_nosl"
        )
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=True).submit(intent("nosl"))
        self.assertEqual(result["state"], "MANUAL_REVIEW_NO_RESUBMIT")
        self.assertEqual(result["reason"], "ACTUAL_FILL_UNSAFE:ACTUAL_POSITION_STOP_MISSING")
        self.assertEqual(self.gateway.containment_calls, 1)

    def test_missing_target_is_contained(self):
        self.gateway.owned_position_snapshot = OwnedPositionSnapshot(
            123456, "XAUUSD.i", "BUY", 0.01, 3000.2, 2999.2, 0.0, 1607101, "R7R1:r6_notp"
        )
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=True).submit(intent("notp"))
        self.assertEqual(result["state"], "MANUAL_REVIEW_NO_RESUBMIT")
        self.assertEqual(result["reason"], "ACTUAL_FILL_UNSAFE:ACTUAL_POSITION_TARGET_MISSING")
        self.assertEqual(self.gateway.containment_calls, 1)

    def test_broker_altered_stop_is_contained(self):
        self.gateway.owned_position_snapshot = OwnedPositionSnapshot(
            123456, "XAUUSD.i", "BUY", 0.01, 3000.2, 2999.1, 3002.2, 1607101, "R7R1:r6_badsl"
        )
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=True).submit(intent("badsl"))
        self.assertEqual(result["state"], "MANUAL_REVIEW_NO_RESUBMIT")
        self.assertEqual(result["reason"], "ACTUAL_FILL_UNSAFE:ACTUAL_STOP_DIFFERS_FROM_SUBMITTED_STOP")
        self.assertEqual(self.gateway.containment_calls, 1)

    def test_containment_failure_still_forces_manual_review(self):
        self.gateway.actual_stop_loss = 6.1
        self.gateway.containment_should_fail = True
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=True).submit(intent("containfail"))
        self.assertEqual(result["state"], "MANUAL_REVIEW_NO_RESUBMIT")
        self.assertEqual(self.gateway.containment_calls, 1)
        self.assertFalse(result["containment"]["ok"])
        self.assertIn("CONTAINMENT_FAILED", result["containment"]["error"])

    def test_post_send_exposure_count_violation_forces_containment(self):
        self.gateway.post_send_exposure = ExposureSnapshot(2, 0, 0.02, 0.0)
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=True).submit(intent("twopos"))
        self.assertEqual(self.gateway.send_calls, 1)
        self.assertEqual(result["state"], "MANUAL_REVIEW_NO_RESUBMIT")
        self.assertEqual(result["reason"], "POST_SEND_EXPOSURE_COUNT_MISMATCH")
        self.assertEqual(self.gateway.containment_calls, 1)

    def test_post_send_volume_violation_forces_containment(self):
        self.gateway.post_send_exposure = ExposureSnapshot(1, 0, 0.03, 0.0)
        result = ExecutionEngine(self.store, self.gateway, execution_enabled=True).submit(intent("overvol"))
        self.assertEqual(result["state"], "MANUAL_REVIEW_NO_RESUBMIT")
        self.assertEqual(result["reason"], "POST_SEND_MAX_EXPOSURE_BREACH")
        self.assertEqual(self.gateway.containment_calls, 1)

    def test_post_send_reconciliation_failure_never_resubmits(self):
        class ReconcileFailGateway(FakeGateway):
            def find_intent_at_broker(self, intent_id):
                if self.send_calls > 0:
                    raise RuntimeError("RECONCILIATION_UNAVAILABLE")
                return BrokerMatch(False)
        gw = ReconcileFailGateway()
        result = ExecutionEngine(self.store, gw, execution_enabled=True).submit(intent("reconfail"))
        self.assertEqual(gw.send_calls, 1)
        self.assertEqual(result["state"], "MANUAL_REVIEW_NO_RESUBMIT")

    def test_restart_never_resubmits_ambiguous_send(self):
        payload = intent("crash").canonical_payload()
        self.store.reserve_intent("crash", payload)
        self.store.transition("crash", "PREFLIGHT_OK")
        self.store.transition("crash", "SUBMITTING")
        self.gateway.recovery_match = BrokerMatch(False)
        recovered = ExecutionEngine(self.store, self.gateway, execution_enabled=True).recover_inflight()
        self.assertEqual(recovered[0]["state"], "MANUAL_REVIEW_NO_RESUBMIT")
        self.assertEqual(self.gateway.send_calls, 0)

    def test_restart_reconciles_safe_existing_position_without_resend(self):
        payload = intent("recover").canonical_payload()
        self.store.reserve_intent("recover", payload)
        self.store.transition("recover", "PREFLIGHT_OK")
        self.store.transition("recover", "SUBMITTING")
        self.gateway.recovery_match = BrokerMatch(True, "POSITION", 123456, "OPEN")
        self.gateway.post_send_exposure = ExposureSnapshot(1, 0, 0.01, 0.0)
        recovered = ExecutionEngine(self.store, self.gateway, execution_enabled=True).recover_inflight()
        self.assertEqual(recovered[0]["state"], "ACKNOWLEDGED")
        self.assertEqual(recovered[0]["actual_fill_safety"]["risk_basis"], "CURRENT_EQUITY_REMAINING_TO_STOP")
        self.assertEqual(self.gateway.send_calls, 0)
        self.assertEqual(self.gateway.containment_calls, 0)

    def test_restart_unsafe_remaining_risk_is_contained_without_resend(self):
        payload = intent("recoverbad").canonical_payload()
        self.store.reserve_intent("recoverbad", payload)
        self.store.transition("recoverbad", "PREFLIGHT_OK")
        self.store.transition("recoverbad", "SUBMITTING")
        self.gateway.recovery_match = BrokerMatch(True, "POSITION", 123456, "OPEN")
        self.gateway.post_send_exposure = ExposureSnapshot(1, 0, 0.01, 0.0)
        self.gateway.remaining_stop_loss = 5.5001
        recovered = ExecutionEngine(self.store, self.gateway, execution_enabled=True).recover_inflight()
        self.assertEqual(recovered[0]["state"], "MANUAL_REVIEW_NO_RESUBMIT")
        self.assertEqual(recovered[0]["reason"], "ACTUAL_FILL_UNSAFE:OPERATING_RISK_CAP_BREACH")
        self.assertEqual(self.gateway.send_calls, 0)
        self.assertEqual(self.gateway.containment_calls, 1)

    def test_audit_chain_verifies(self):
        self.store.append_event("A", {"x": 1})
        self.store.append_event("B", {"y": 2})
        self.assertTrue(self.store.verify_chain())


if __name__ == "__main__":
    unittest.main()
