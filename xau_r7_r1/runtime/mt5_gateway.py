from __future__ import annotations

import math
import time
from dataclasses import asdict
from typing import Dict, List, Tuple

from .constants import (
    COMMENT_PREFIX,
    DEMO_ONLY,
    HARD_MAX_SPREAD_USD,
    HARD_MAX_TICK_AGE_SECONDS,
    MAGIC,
    REQUIRED_ACCOUNT_CURRENCY,
    SYMBOL,
)
from .models import AccountSnapshot, BrokerMatch, ExposureSnapshot, OrderIntent, SymbolSnapshot


class GatewayError(RuntimeError):
    pass


class MT5Gateway:
    def __init__(self, *, max_tick_age_seconds: float = HARD_MAX_TICK_AGE_SECONDS, max_spread_usd: float = HARD_MAX_SPREAD_USD):
        if max_tick_age_seconds <= 0 or max_tick_age_seconds > HARD_MAX_TICK_AGE_SECONDS:
            raise GatewayError("TICK_AGE_LIMIT_MAY_NOT_EXCEED_HARD_MAX")
        if max_spread_usd <= 0 or max_spread_usd > HARD_MAX_SPREAD_USD:
            raise GatewayError("SPREAD_LIMIT_MAY_NOT_EXCEED_HARD_MAX")
        self.max_tick_age_seconds = float(max_tick_age_seconds)
        self.max_spread_usd = float(max_spread_usd)
        self.mt5 = None

    def connect(self) -> None:
        try:
            import MetaTrader5 as mt5
        except Exception as exc:
            raise GatewayError("METATRADER5_PYTHON_PACKAGE_NOT_AVAILABLE") from exc
        if not mt5.initialize():
            raise GatewayError(f"MT5_INITIALIZE_FAILED:{mt5.last_error()}")
        self.mt5 = mt5
        account = mt5.account_info()
        if account is None:
            self.shutdown()
            raise GatewayError("MT5_ACCOUNT_INFO_UNAVAILABLE")
        if str(account.currency).upper() != REQUIRED_ACCOUNT_CURRENCY:
            self.shutdown()
            raise GatewayError(f"ACCOUNT_CURRENCY_MISMATCH:{account.currency}")
        if DEMO_ONLY and "demo" not in str(account.server or "").lower():
            self.shutdown()
            raise GatewayError(f"DEMO_ONLY_GUARD:{account.server}")
        if not mt5.symbol_select(SYMBOL, True):
            self.shutdown()
            raise GatewayError(f"SYMBOL_NOT_AVAILABLE:{SYMBOL}")

    def shutdown(self) -> None:
        if self.mt5 is not None:
            try:
                self.mt5.shutdown()
            finally:
                self.mt5 = None

    def _require(self):
        if self.mt5 is None:
            raise GatewayError("MT5_NOT_CONNECTED")
        return self.mt5

    def account_snapshot(self) -> AccountSnapshot:
        mt5 = self._require()
        a = mt5.account_info()
        if a is None:
            raise GatewayError("MT5_ACCOUNT_INFO_UNAVAILABLE")
        return AccountSnapshot(
            login=int(a.login),
            server=str(a.server),
            currency=str(a.currency),
            equity_sgd=float(a.equity),
            balance_sgd=float(a.balance),
            margin_free_sgd=float(a.margin_free),
        )

    def symbol_snapshot(self) -> SymbolSnapshot:
        mt5 = self._require()
        info = mt5.symbol_info(SYMBOL)
        tick = mt5.symbol_info_tick(SYMBOL)
        if info is None or tick is None:
            raise GatewayError("MT5_SYMBOL_OR_TICK_UNAVAILABLE")
        tick_ts = float(getattr(tick, "time_msc", 0) or 0) / 1000.0
        if tick_ts <= 0:
            tick_ts = float(tick.time)
        age = time.time() - tick_ts
        bid, ask = float(tick.bid), float(tick.ask)
        if age < -2.0 or age > self.max_tick_age_seconds:
            raise GatewayError(f"STALE_OR_FUTURE_TICK:{age:.3f}s")
        if bid <= 0 or ask <= 0 or ask < bid:
            raise GatewayError("INVALID_MARKET_QUOTE")
        if ask - bid > self.max_spread_usd:
            raise GatewayError(f"SPREAD_GUARD:{ask- bid:.5f}")
        return SymbolSnapshot(
            symbol=SYMBOL,
            bid=bid,
            ask=ask,
            tick_time_epoch=tick_ts,
            tick_age_seconds=age,
            volume_min=float(info.volume_min),
            volume_step=float(info.volume_step),
            volume_max=float(info.volume_max),
            point=float(info.point),
            trade_stops_level_points=int(info.trade_stops_level),
        )

    def exposure_snapshot(self) -> ExposureSnapshot:
        mt5 = self._require()
        positions = list(mt5.positions_get(symbol=SYMBOL) or [])
        orders = list(mt5.orders_get(symbol=SYMBOL) or [])
        return ExposureSnapshot(
            position_count=len(positions),
            pending_order_count=len(orders),
            total_position_lot=sum(float(p.volume) for p in positions),
            total_pending_lot=sum(float(o.volume_current) for o in orders),
        )

    @staticmethod
    def _lot_on_step(lot: float, minimum: float, step: float) -> bool:
        if step <= 0:
            return False
        units = (lot - minimum) / step
        return abs(units - round(units)) <= 1e-9

    def validate_broker_geometry(self, intent: OrderIntent, symbol: SymbolSnapshot, entry_price: float) -> None:
        lot = float(intent.lot)
        if lot < symbol.volume_min - 1e-12 or lot > symbol.volume_max + 1e-12:
            raise GatewayError("BROKER_VOLUME_RANGE_REJECT")
        if not self._lot_on_step(lot, symbol.volume_min, symbol.volume_step):
            raise GatewayError("BROKER_VOLUME_STEP_REJECT")
        side = intent.side.upper()
        stop = float(intent.stop_price)
        if side == "BUY" and stop >= entry_price:
            raise GatewayError("BUY_STOP_NOT_BELOW_ENTRY")
        if side == "SELL" and stop <= entry_price:
            raise GatewayError("SELL_STOP_NOT_ABOVE_ENTRY")
        if side not in {"BUY", "SELL"}:
            raise GatewayError("UNSUPPORTED_SIDE")
        min_distance = symbol.trade_stops_level_points * symbol.point
        if abs(entry_price - stop) + 1e-12 < min_distance:
            raise GatewayError("BROKER_STOPS_LEVEL_REJECT")

    def current_market_entry(self, side: str, symbol: SymbolSnapshot) -> float:
        side = side.upper()
        if side == "BUY":
            return symbol.ask
        if side == "SELL":
            return symbol.bid
        raise GatewayError("UNSUPPORTED_SIDE")

    def projected_stop_loss_sgd(self, intent: OrderIntent, entry_price: float) -> float:
        mt5 = self._require()
        side = intent.side.upper()
        order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL if side == "SELL" else None
        if order_type is None:
            raise GatewayError("UNSUPPORTED_SIDE")
        pnl = mt5.order_calc_profit(order_type, SYMBOL, float(intent.lot), float(entry_price), float(intent.stop_price))
        if pnl is None:
            raise GatewayError(f"ORDER_CALC_PROFIT_FAILED:{mt5.last_error()}")
        pnl = float(pnl)
        if not math.isfinite(pnl) or pnl >= 0:
            raise GatewayError(f"INVALID_PROJECTED_STOP_PNL:{pnl}")
        return -pnl

    def build_market_request(self, intent: OrderIntent, entry_price: float) -> Dict:
        mt5 = self._require()
        side = intent.side.upper()
        order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL if side == "SELL" else None
        if order_type is None:
            raise GatewayError("UNSUPPORTED_SIDE")
        comment = (COMMENT_PREFIX + intent.client_intent_id)[:31]
        return {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": SYMBOL,
            "volume": float(intent.lot),
            "type": order_type,
            "price": float(entry_price),
            "sl": float(intent.stop_price),
            "tp": float(intent.take_profit_price or 0.0),
            "deviation": 10,
            "magic": MAGIC,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

    def order_check(self, request: Dict):
        mt5 = self._require()
        check = mt5.order_check(request)
        if check is None:
            raise GatewayError(f"ORDER_CHECK_NONE:{mt5.last_error()}")
        if int(check.retcode) != 0:
            raise GatewayError(f"ORDER_CHECK_REJECTED:{check.retcode}:{check.comment}")
        return check

    def order_send(self, request: Dict):
        mt5 = self._require()
        result = mt5.order_send(request)
        if result is None:
            raise GatewayError(f"ORDER_SEND_NONE:{mt5.last_error()}")
        allowed = {int(mt5.TRADE_RETCODE_DONE), int(mt5.TRADE_RETCODE_PLACED), int(mt5.TRADE_RETCODE_DONE_PARTIAL)}
        if int(result.retcode) not in allowed:
            raise GatewayError(f"ORDER_SEND_REJECTED:{result.retcode}:{result.comment}")
        return result

    def find_intent_at_broker(self, client_intent_id: str) -> BrokerMatch:
        mt5 = self._require()
        needle = (COMMENT_PREFIX + client_intent_id)[:31]
        for p in mt5.positions_get(symbol=SYMBOL) or []:
            if int(p.magic) == MAGIC and str(getattr(p, "comment", "")) == needle:
                return BrokerMatch(True, "POSITION", int(p.ticket), "OPEN")
        for o in mt5.orders_get(symbol=SYMBOL) or []:
            if int(o.magic) == MAGIC and str(getattr(o, "comment", "")) == needle:
                return BrokerMatch(True, "ORDER", int(o.ticket), "PENDING")
        # History is checked as well so a fast fill/close cannot look like a lost submission.
        now = time.time()
        deals = mt5.history_deals_get(now - 7 * 86400, now) or []
        for d in deals:
            if int(getattr(d, "magic", 0)) == MAGIC and str(getattr(d, "comment", "")) == needle:
                return BrokerMatch(True, "DEAL", int(d.ticket), "HISTORICAL")
        return BrokerMatch(False)
