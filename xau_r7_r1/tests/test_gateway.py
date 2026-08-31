from __future__ import annotations

import unittest
from types import SimpleNamespace

from r7_runtime.models import OrderIntent
from r7_runtime.mt5_gateway import GatewayError, MT5Gateway


class FakeMT5:
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_RETURN = 2
    SYMBOL_FILLING_IOC = 2
    SYMBOL_FILLING_FOK = 1
    SYMBOL_TRADE_EXECUTION_MARKET = 2

    def __init__(self):
        self.positions_value = ()
        self.orders_value = ()
        self.deals_value = ()
        self.profit_value = -5.0

    def last_error(self):
        return (1, "fake")

    def positions_get(self, **kwargs):
        return self.positions_value

    def orders_get(self, **kwargs):
        return self.orders_value

    def history_deals_get(self, start, end):
        return self.deals_value

    def order_calc_profit(self, order_type, symbol, lot, entry, stop):
        return self.profit_value


class GatewayTests(unittest.TestCase):
    def gateway(self):
        gw = MT5Gateway()
        gw.mt5 = FakeMT5()
        return gw

    def test_projected_stop_loss_includes_frozen_round_turn_commission(self):
        gw = self.gateway()
        intent = OrderIntent("x", "BUY", 0.01, 2999.0, 3002.0, "BASE")
        loss = gw.projected_stop_loss_sgd(intent, 3000.0)
        self.assertAlmostEqual(loss, 5.0945, places=9)

    def test_commission_scales_with_lot(self):
        gw = self.gateway()
        gw.mt5.profit_value = -10.0
        intent = OrderIntent("x", "BUY", 0.02, 2999.0, 3002.0, "BASE")
        loss = gw.projected_stop_loss_sgd(intent, 3000.0)
        self.assertAlmostEqual(loss, 10.189, places=9)

    def test_positions_query_none_fails_closed(self):
        gw = self.gateway()
        gw.mt5.positions_value = None
        with self.assertRaises(GatewayError):
            gw.exposure_snapshot()

    def test_orders_query_none_fails_closed(self):
        gw = self.gateway()
        gw.mt5.orders_value = None
        with self.assertRaises(GatewayError):
            gw.exposure_snapshot()

    def test_history_query_none_fails_closed(self):
        gw = self.gateway()
        gw.mt5.deals_value = None
        with self.assertRaises(GatewayError):
            gw.find_intent_at_broker("missing")

    def test_empty_exposure_is_not_an_error(self):
        gw = self.gateway()
        exposure = gw.exposure_snapshot()
        self.assertEqual(exposure.total_count, 0)
        self.assertEqual(exposure.total_lot, 0.0)

    def test_invalid_nonloss_stop_projection_fails_closed(self):
        gw = self.gateway()
        gw.mt5.profit_value = 0.0
        intent = OrderIntent("x", "BUY", 0.01, 2999.0, 3002.0, "BASE")
        with self.assertRaises(GatewayError):
            gw.projected_stop_loss_sgd(intent, 3000.0)


if __name__ == "__main__":
    unittest.main()
