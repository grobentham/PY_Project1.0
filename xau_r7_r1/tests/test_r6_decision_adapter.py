from __future__ import annotations

import json
import unittest

from r7_runtime.constants import CANONICAL_R6_ZIP_SHA256
from r7_runtime.models import SymbolSnapshot
from r7_runtime.r6_decision_adapter import DecisionAdapterError, R6DecisionAdapter

NOW = 1_800_000_000_000


def decision(**updates):
    d = {
        "schema": "V16_R6_ADMITTED_DECISION_V1",
        "policy": "FROZEN_V16_R6",
        "parent_zip_sha256": CANONICAL_R6_ZIP_SHA256,
        "decision_id": "decision-001",
        "signal_bar_ms": NOW - 1000,
        "emitted_at_ms": NOW - 500,
        "side": 1,
        "source": "TIME_LANE",
        "priority": 1,
        "family": "LIQUIDITY_TRANSITION_MOMENTUM",
        "signal_type": "",
        "atr_usd": 2.5,
        "stop_atr": 1.2,
        "target_atr": 2.4,
        "geometry_used": "PRIMARY_1P2_2P4",
        "lot_size": 0.01,
        "admitted": True,
    }
    d.update(updates)
    return d


def raw(d):
    return json.dumps(d, sort_keys=True, separators=(",", ":"), allow_nan=True).encode()


def symbol(bid=3000.10, ask=3000.20):
    return SymbolSnapshot(
        symbol="XAUUSD.i", bid=bid, ask=ask, tick_time_epoch=1.0,
        tick_age_seconds=0.1, volume_min=0.01, volume_step=0.01,
        volume_max=100.0, point=0.01, trade_stops_level_points=0,
    )


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.a = R6DecisionAdapter()

    def test_ltm_primary_translates_and_carries_frozen_geometry(self):
        x = self.a.adapt(raw(decision()), symbol(), now_ms=NOW)
        self.assertEqual(x.intent.side, "BUY")
        self.assertAlmostEqual(x.intent.stop_price, 2997.20)
        self.assertAlmostEqual(x.intent.take_profit_price, 3006.20)
        self.assertEqual(x.intent.frozen_atr_usd, 2.5)
        self.assertEqual(x.intent.frozen_stop_atr, 1.2)
        self.assertEqual(x.intent.frozen_target_atr, 2.4)
        self.assertEqual(len(x.decision_fingerprint), 64)

    def test_ltm_fallback_allowed(self):
        d = decision(stop_atr=1.0, target_atr=2.0, geometry_used="FALLBACK_1P0_2P0", side=-1)
        x = self.a.adapt(raw(d), symbol(), now_ms=NOW)
        self.assertEqual(x.intent.side, "SELL")
        self.assertAlmostEqual(x.intent.stop_price, 3002.60)
        self.assertAlmostEqual(x.intent.take_profit_price, 2995.10)

    def test_compression_primary_allowed(self):
        d = decision(source="COMPRESSION_LANE", priority=2, family="COMPRESSION_EXPANSION_BREAKOUT", stop_atr=1.0, target_atr=2.0, geometry_used="PRIMARY")
        self.a.parse(raw(d), now_ms=NOW)

    def test_core_explicit_geometry_is_carried_not_inferred(self):
        d = decision(source="CORE", priority=0, family="", signal_type="MTF_BB_REENTRY", stop_atr=1.6, target_atr=1.5, geometry_used="PRIMARY")
        x = self.a.adapt(raw(d), symbol(), now_ms=NOW)
        self.assertEqual(x.intent.frozen_stop_atr, 1.6)
        self.assertEqual(x.intent.frozen_target_atr, 1.5)

    def test_retired_source_rejected(self):
        d = decision(source="AUX_RF_LTM", priority=4)
        with self.assertRaisesRegex(DecisionAdapterError, "RETIRED"):
            self.a.parse(raw(d), now_ms=NOW)

    def test_source_priority_mismatch_rejected(self):
        with self.assertRaisesRegex(DecisionAdapterError, "PRIORITY"):
            self.a.parse(raw(decision(priority=5)), now_ms=NOW)

    def test_source_family_mismatch_rejected(self):
        with self.assertRaisesRegex(DecisionAdapterError, "FAMILY"):
            self.a.parse(raw(decision(family="COMPRESSION_EXPANSION_BREAKOUT")), now_ms=NOW)

    def test_parent_and_policy_mismatch_rejected(self):
        with self.assertRaisesRegex(DecisionAdapterError, "PARENT"):
            self.a.parse(raw(decision(parent_zip_sha256="0" * 64)), now_ms=NOW)
        with self.assertRaisesRegex(DecisionAdapterError, "POLICY"):
            self.a.parse(raw(decision(policy="OTHER")), now_ms=NOW)

    def test_not_admitted_rejected(self):
        with self.assertRaisesRegex(DecisionAdapterError, "NOT_ADMITTED"):
            self.a.parse(raw(decision(admitted=False)), now_ms=NOW)

    def test_nonfinite_atr_rejected(self):
        payload = raw(decision(atr_usd=float("nan")))
        with self.assertRaisesRegex(DecisionAdapterError, "NONFINITE"):
            self.a.parse(payload, now_ms=NOW)

    def test_bad_geometry_pair_rejected(self):
        with self.assertRaisesRegex(DecisionAdapterError, "GEOMETRY_MISMATCH"):
            self.a.parse(raw(decision(stop_atr=1.1)), now_ms=NOW)

    def test_lot_above_frozen_ceiling_rejected(self):
        with self.assertRaisesRegex(DecisionAdapterError, "LOT_OUTSIDE"):
            self.a.parse(raw(decision(lot_size=0.03)), now_ms=NOW)

    def test_stale_and_future_decisions_rejected(self):
        with self.assertRaisesRegex(DecisionAdapterError, "STALE"):
            self.a.parse(raw(decision(emitted_at_ms=NOW - 301000, signal_bar_ms=NOW - 302000)), now_ms=NOW)
        with self.assertRaisesRegex(DecisionAdapterError, "FUTURE"):
            self.a.parse(raw(decision(emitted_at_ms=NOW + 3000, signal_bar_ms=NOW + 2000)), now_ms=NOW)

    def test_old_signal_cannot_be_revived_by_fresh_emission_timestamp(self):
        d = decision(signal_bar_ms=NOW - 301000, emitted_at_ms=NOW - 500)
        with self.assertRaisesRegex(DecisionAdapterError, "SIGNAL_STALE"):
            self.a.parse(raw(d), now_ms=NOW)

    def test_same_decision_is_idempotent_across_market_quotes(self):
        a = self.a.adapt(raw(decision()), symbol(3000.1, 3000.2), now_ms=NOW).intent
        b = self.a.adapt(raw(decision()), symbol(3010.1, 3010.2), now_ms=NOW).intent
        self.assertEqual(a.client_intent_id, b.client_intent_id)
        self.assertEqual(a.canonical_payload(), b.canonical_payload())
        self.assertNotEqual(a.stop_price, b.stop_price)


if __name__ == "__main__":
    unittest.main()
