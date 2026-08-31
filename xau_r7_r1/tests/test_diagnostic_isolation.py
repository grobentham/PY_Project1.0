from __future__ import annotations

import unittest

from r7_runtime.models import AccountSnapshot, BrokerMatch, ExposureSnapshot, OrderIntent, SymbolSnapshot
from r7_runtime.runtime import diagnostic_preflight


class DiagnosticGateway:
    def account_snapshot(self):
        return AccountSnapshot(1, "BlueberryMarkets-Demo", "SGD", 1000.0, 1000.0, 1000.0)

    def symbol_snapshot(self):
        return SymbolSnapshot("XAUUSD.i", 3000.0, 3000.2, 1.0, 0.1, 0.01, 0.01, 100.0, 0.01, 0)

    def exposure_snapshot(self):
        return ExposureSnapshot(0, 0, 0.0, 0.0)

    def current_market_entry(self, side, symbol):
        return symbol.ask if side.upper() == "BUY" else symbol.bid

    def validate_broker_geometry(self, intent, symbol, entry):
        return None

    def projected_stop_loss_sgd(self, intent, entry):
        return 5.0

    def build_market_request(self, intent, entry):
        return {
            "price": entry,
            "symbol": "XAUUSD.i",
            "volume": intent.lot,
            "sl": intent.stop_price,
            "tp": intent.take_profit_price,
        }

    def order_check(self, request):
        return True

    def find_intent_at_broker(self, intent_id):
        return BrokerMatch(False)


class DiagnosticIsolationTests(unittest.TestCase):
    def test_raw_preflight_uses_ephemeral_state_and_never_sends(self):
        intent = OrderIntent("diag_1", "BUY", 0.01, 2999.0, 3002.0, "DIAGNOSTIC")
        result = diagnostic_preflight(DiagnosticGateway(), intent)
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "DRY_RUN_COMPLETE")
        self.assertFalse(result["send_attempted"])
        self.assertTrue(result["diagnostic_ephemeral_state"])
        self.assertFalse(result["operational_ledger_touched"])


if __name__ == "__main__":
    unittest.main()
