from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from .constants import (
    COMMENT_PREFIX,
    COMMISSION_RT_SGD_PER_001_LOT,
    DEMO_ONLY,
    HARD_MAX_SPREAD_USD,
    HARD_MAX_TICK_AGE_SECONDS,
    MAGIC,
    REQUIRED_ACCOUNT_CURRENCY,
    REQUIRED_BROKER_SERVER_TOKEN,
    SYMBOL,
)
from .models import AccountSnapshot, BrokerMatch, ExposureSnapshot, OrderIntent, SymbolSnapshot


class GatewayError(RuntimeError):
    pass


class MT5Gateway:
    def __init__(self, *, max_tick_age_seconds: float = HARD_MAX_TICK_AGE_SECONDS, max_spread_usd: float = HARD_MAX_SPREAD_USD):
        if not math.isfinite(float(max_tick_age_seconds)) or max_tick_age_seconds <= 0 or max_tick_age_seconds > HARD_MAX_TICK_AGE_SECONDS:
            raise GatewayError("TICK_AGE_LIMIT_MAY_NOT_EXCEED_HARD_MAX")
        if not math.isfinite(float(max_spread_usd)) or max_spread_usd <= 0 or max_spread_usd > HARD_MAX_SPREAD_USD:
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
        server = str(account.server or "")
        if REQUIRED_BROKER_SERVER_TOKEN not in server.lower():
            self.shutdown()
            raise GatewayError(f"BROKER_SERVER_MISMATCH:{server}")
        if DEMO_ONLY and "demo" not in server.lower():
            self.shutdown()
            raise GatewayError(f"DEMO_ONLY_GUARD:{server}")
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

    def _positions(self) -> List:
        mt5 = self._require()
        rows = mt5.positions_get(symbol=SYMBOL)
        if rows is None:
            raise GatewayError(f"MT5_POSITIONS_QUERY_FAILED:{mt5.last_error()}")
        return list(rows)

    def _orders(self) -> List:
        mt5 = self._require()
        rows = mt5.orders_get(symbol=SYMBOL)
        if rows is None:
            raise GatewayError(f"MT5_ORDERS_QUERY_FAILED:{mt5.last_error()}")
        return list(rows)

    def _recent_deals(self, days: int = 30) -> List:
        mt5 = self._require()
        to_dt = datetime.now(timezone.utc)
        from_dt = to_dt - timedelta(days=days)
        rows = mt5.history_deals_get(from_dt, to_dt)
        if rows is None:
            raise GatewayError(f"MT5_HISTORY_DEALS_QUERY_FAILED:{mt5.last_error()}")
        return list(rows)

    def assert_trading_permissions(self) -> None:
        mt5 = self._require()
        terminal = mt5.terminal_info()
        account = mt5.account_info()
        info = mt5.symbol_info(SYMBOL)
        if terminal is None or account is None or info is None:
            raise GatewayError("MT5_TRADING_PERMISSION_STATE_UNAVAILABLE")
        if not bool(getattr(terminal, "trade_allowed", False)):
            raise GatewayError("MT5_TERMINAL_AUTOTRADING_DISABLED")
        if not bool(getattr(account, "trade_allowed", False)):
            raise GatewayError("MT5_ACCOUNT_TRADING_DISABLED")
        if hasattr(account, "trade_expert") and not bool(getattr(account, "trade_expert")):
            raise GatewayError("MT5_ACCOUNT_EXPERT_TRADING_DISABLED")
        disabled = int(getattr(mt5, "SYMBOL_TRADE_MODE_DISABLED", 0))
        if int(getattr(info, "trade_mode", disabled)) == disabled:
            raise GatewayError("MT5_SYMBOL_TRADING_DISABLED")

    def account_snapshot(self) -> AccountSnapshot:
        mt5 = self._require()
        a = mt5.account_info()
        if a is None:
            raise GatewayError("MT5_ACCOUNT_INFO_UNAVAILABLE")
        equity = float(a.equity)
        balance = float(a.balance)
        margin_free = float(a.margin_free)
        if not all(math.isfinite(v) for v in (equity, balance, margin_free)):
            raise GatewayError("INVALID_ACCOUNT_NUMERIC_STATE")
        return AccountSnapshot(
            login=int(a.login),
            server=str(a.server),
            currency=str(a.currency),
            equity_sgd=equity,
            balance_sgd=balance,
            margin_free_sgd=margin_free,
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
        now = datetime.now(timezone.utc).timestamp()
        age = now - tick_ts
        bid, ask = float(tick.bid), float(tick.ask)
        volume_min = float(info.volume_min)
        volume_step = float(info.volume_step)
        volume_max = float(info.volume_max)
        point = float(info.point)
        if not all(math.isfinite(v) for v in (tick_ts, age, bid, ask, volume_min, volume_step, volume_max, point)):
            raise GatewayError("INVALID_SYMBOL_NUMERIC_STATE")
        if age < -2.0 or age > self.max_tick_age_seconds:
            raise GatewayError(f"STALE_OR_FUTURE_TICK:{age:.3f}s")
        if bid <= 0 or ask <= 0 or ask < bid:
            raise GatewayError("INVALID_MARKET_QUOTE")
        if ask - bid > self.max_spread_usd:
            raise GatewayError(f"SPREAD_GUARD:{ask - bid:.5f}")
        if volume_min <= 0 or volume_step <= 0 or volume_max < volume_min or point <= 0:
            raise GatewayError("INVALID_BROKER_SYMBOL_GEOMETRY")
        return SymbolSnapshot(
            symbol=SYMBOL,
            bid=bid,
            ask=ask,
            tick_time_epoch=tick_ts,
            tick_age_seconds=age,
            volume_min=volume_min,
            volume_step=volume_step,
            volume_max=volume_max,
            point=point,
            trade_stops_level_points=int(info.trade_stops_level),
        )

    def exposure_snapshot(self) -> ExposureSnapshot:
        positions = self._positions()
        orders = self._orders()
        position_lot = sum(float(p.volume) for p in positions)
        pending_lot = sum(float(o.volume_current) for o in orders)
        if not math.isfinite(position_lot) or not math.isfinite(pending_lot) or position_lot < 0 or pending_lot < 0:
            raise GatewayError("INVALID_BROKER_EXPOSURE_STATE")
        return ExposureSnapshot(
            position_count=len(positions),
            pending_order_count=len(orders),
            total_position_lot=position_lot,
            total_pending_lot=pending_lot,
        )

    @staticmethod
    def _lot_on_step(lot: float, minimum: float, step: float) -> bool:
        if step <= 0:
            return False
        units = (lot - minimum) / step
        return math.isfinite(units) and abs(units - round(units)) <= 1e-9

    def validate_broker_geometry(self, intent: OrderIntent, symbol: SymbolSnapshot, entry_price: float) -> None:
        lot = float(intent.lot)
        stop = float(intent.stop_price)
        tp = None if intent.take_profit_price is None else float(intent.take_profit_price)
        entry_price = float(entry_price)
        values = [lot, stop, entry_price] + ([] if tp is None else [tp])
        if not all(math.isfinite(v) for v in values):
            raise GatewayError("NONFINITE_ORDER_GEOMETRY")
        if lot < symbol.volume_min - 1e-12 or lot > symbol.volume_max + 1e-12:
            raise GatewayError("BROKER_VOLUME_RANGE_REJECT")
        if not self._lot_on_step(lot, symbol.volume_min, symbol.volume_step):
            raise GatewayError("BROKER_VOLUME_STEP_REJECT")
        side = intent.side.upper()
        if side == "BUY":
            if stop >= entry_price:
                raise GatewayError("BUY_STOP_NOT_BELOW_ENTRY")
            if tp is not None and tp <= entry_price:
                raise GatewayError("BUY_TARGET_NOT_ABOVE_ENTRY")
        elif side == "SELL":
            if stop <= entry_price:
                raise GatewayError("SELL_STOP_NOT_ABOVE_ENTRY")
            if tp is not None and tp >= entry_price:
                raise GatewayError("SELL_TARGET_NOT_BELOW_ENTRY")
        else:
            raise GatewayError("UNSUPPORTED_SIDE")
        min_distance = max(0, int(symbol.trade_stops_level_points)) * symbol.point
        if abs(entry_price - stop) + 1e-12 < min_distance:
            raise GatewayError("BROKER_STOPS_LEVEL_REJECT")
        if tp is not None and abs(entry_price - tp) + 1e-12 < min_distance:
            raise GatewayError("BROKER_TARGET_STOPS_LEVEL_REJECT")

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
        commission = COMMISSION_RT_SGD_PER_001_LOT * (float(intent.lot) / 0.01)
        projected = (-pnl) + commission
        if not math.isfinite(projected) or projected <= 0:
            raise GatewayError(f"INVALID_PROJECTED_STOP_WITH_COMMISSION:{projected}")
        return projected

    def _select_filling_mode(self) -> int:
        mt5 = self._require()
        info = mt5.symbol_info(SYMBOL)
        if info is None:
            raise GatewayError("MT5_SYMBOL_INFO_UNAVAILABLE_FOR_FILLING")
        flags = int(getattr(info, "filling_mode", 0))
        symbol_ioc = int(getattr(mt5, "SYMBOL_FILLING_IOC", 2))
        symbol_fok = int(getattr(mt5, "SYMBOL_FILLING_FOK", 1))
        if flags & symbol_ioc:
            return int(mt5.ORDER_FILLING_IOC)
        if flags & symbol_fok:
            return int(mt5.ORDER_FILLING_FOK)
        execution_market = int(getattr(mt5, "SYMBOL_TRADE_EXECUTION_MARKET", 2))
        if int(getattr(info, "trade_exemode", execution_market)) == execution_market:
            raise GatewayError("NO_SUPPORTED_MARKET_FILLING_MODE")
        return int(mt5.ORDER_FILLING_RETURN)

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
            "type_filling": self._select_filling_mode(),
        }

    def order_check(self, request: Dict):
        mt5 = self._require()
        self.assert_trading_permissions()
        check = mt5.order_check(request)
        if check is None:
            raise GatewayError(f"ORDER_CHECK_NONE:{mt5.last_error()}")
        if int(check.retcode) != 0:
            raise GatewayError(f"ORDER_CHECK_REJECTED:{check.retcode}:{check.comment}")
        return check

    def order_send(self, request: Dict):
        mt5 = self._require()
        self.assert_trading_permissions()
        result = mt5.order_send(request)
        if result is None:
            raise GatewayError(f"ORDER_SEND_NONE:{mt5.last_error()}")
        allowed = {int(mt5.TRADE_RETCODE_DONE), int(mt5.TRADE_RETCODE_PLACED), int(mt5.TRADE_RETCODE_DONE_PARTIAL)}
        if int(result.retcode) not in allowed:
            raise GatewayError(f"ORDER_SEND_REJECTED:{result.retcode}:{result.comment}")
        return result

    def find_intent_at_broker(self, client_intent_id: str) -> BrokerMatch:
        needle = (COMMENT_PREFIX + client_intent_id)[:31]
        for p in self._positions():
            if int(p.magic) == MAGIC and str(getattr(p, "comment", "")) == needle:
                return BrokerMatch(True, "POSITION", int(p.ticket), "OPEN")
        for o in self._orders():
            if int(o.magic) == MAGIC and str(getattr(o, "comment", "")) == needle:
                return BrokerMatch(True, "ORDER", int(o.ticket), "PENDING")
        for d in self._recent_deals(days=30):
            if int(getattr(d, "magic", 0)) == MAGIC and str(getattr(d, "comment", "")) == needle:
                return BrokerMatch(True, "DEAL", int(d.ticket), "HISTORICAL")
        return BrokerMatch(False)
