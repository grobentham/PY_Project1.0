from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .constants import (
    COMMENT_PREFIX,
    COMMISSION_RT_SGD_PER_001_LOT,
    DEMO_ONLY,
    EMERGENCY_CLOSE_DEVIATION_POINTS,
    HARD_MAX_SPREAD_USD,
    HARD_MAX_TICK_AGE_SECONDS,
    MAGIC,
    ORDER_DEVIATION_POINTS,
    REQUIRED_ACCOUNT_CURRENCY,
    REQUIRED_BROKER_SERVER_TOKEN,
    SYMBOL,
)
from .models import AccountSnapshot, BrokerMatch, ExposureSnapshot, OrderIntent, OwnedPositionSnapshot, SymbolSnapshot


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
        self.connected_login: Optional[int] = None
        self.connected_server: Optional[str] = None

    def connect(self) -> None:
        try:
            import MetaTrader5 as mt5
        except Exception as exc:
            raise GatewayError("METATRADER5_PYTHON_PACKAGE_NOT_AVAILABLE") from exc
        if not mt5.initialize():
            raise GatewayError(f"MT5_INITIALIZE_FAILED:{mt5.last_error()}")
        self.mt5 = mt5
        try:
            account = mt5.account_info()
            if account is None:
                raise GatewayError("MT5_ACCOUNT_INFO_UNAVAILABLE")
            self._validate_account_identity(account, pin=False)
            self.connected_login = int(account.login)
            self.connected_server = str(account.server or "")
            if not mt5.symbol_select(SYMBOL, True):
                raise GatewayError(f"SYMBOL_NOT_AVAILABLE:{SYMBOL}")
            terminal = mt5.terminal_info()
            if terminal is None or not bool(getattr(terminal, "connected", False)):
                raise GatewayError("MT5_TERMINAL_NOT_CONNECTED")
        except Exception:
            self.shutdown()
            raise

    def shutdown(self) -> None:
        if self.mt5 is not None:
            try:
                self.mt5.shutdown()
            finally:
                self.mt5 = None
                self.connected_login = None
                self.connected_server = None

    def _require(self):
        if self.mt5 is None:
            raise GatewayError("MT5_NOT_CONNECTED")
        return self.mt5

    def _validate_account_identity(self, account, *, pin: bool = True) -> None:
        mt5 = self._require()
        server = str(account.server or "")
        if str(account.currency).upper() != REQUIRED_ACCOUNT_CURRENCY:
            raise GatewayError(f"ACCOUNT_CURRENCY_MISMATCH:{account.currency}")
        if REQUIRED_BROKER_SERVER_TOKEN not in server.lower():
            raise GatewayError(f"BROKER_SERVER_MISMATCH:{server}")
        if DEMO_ONLY and "demo" not in server.lower():
            raise GatewayError(f"DEMO_ONLY_GUARD:{server}")
        demo_mode = int(getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0))
        if DEMO_ONLY and int(getattr(account, "trade_mode", -1)) != demo_mode:
            raise GatewayError(f"ACCOUNT_TRADE_MODE_NOT_DEMO:{getattr(account, 'trade_mode', None)}")
        if pin and self.connected_login is not None:
            if int(account.login) != self.connected_login:
                raise GatewayError(f"ACCOUNT_SWITCH_DETECTED:{self.connected_login}->{account.login}")
            if self.connected_server is not None and server != self.connected_server:
                raise GatewayError(f"ACCOUNT_SERVER_SWITCH_DETECTED:{self.connected_server}->{server}")

    def _account_info_checked(self):
        mt5 = self._require()
        account = mt5.account_info()
        if account is None:
            raise GatewayError("MT5_ACCOUNT_INFO_UNAVAILABLE")
        self._validate_account_identity(account, pin=True)
        return account

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

    def _symbol_info_checked(self):
        mt5 = self._require()
        info = mt5.symbol_info(SYMBOL)
        if info is None:
            raise GatewayError("MT5_SYMBOL_INFO_UNAVAILABLE")
        return info

    def assert_trading_permissions(self, side: Optional[str] = None, *, for_close: bool = False) -> None:
        mt5 = self._require()
        terminal = mt5.terminal_info()
        account = self._account_info_checked()
        info = self._symbol_info_checked()
        if terminal is None:
            raise GatewayError("MT5_TERMINAL_INFO_UNAVAILABLE")
        if not bool(getattr(terminal, "connected", False)):
            raise GatewayError("MT5_TERMINAL_NOT_CONNECTED")
        if bool(getattr(terminal, "tradeapi_disabled", False)):
            raise GatewayError("MT5_PYTHON_TRADE_API_DISABLED")
        if not bool(getattr(terminal, "trade_allowed", False)):
            raise GatewayError("MT5_TERMINAL_AUTOTRADING_DISABLED")
        if not bool(getattr(account, "trade_allowed", False)):
            raise GatewayError("MT5_ACCOUNT_TRADING_DISABLED")
        if hasattr(account, "trade_expert") and not bool(getattr(account, "trade_expert")):
            raise GatewayError("MT5_ACCOUNT_EXPERT_TRADING_DISABLED")

        trade_mode = int(getattr(info, "trade_mode", -1))
        disabled = int(getattr(mt5, "SYMBOL_TRADE_MODE_DISABLED", 0))
        long_only = int(getattr(mt5, "SYMBOL_TRADE_MODE_LONGONLY", 1))
        short_only = int(getattr(mt5, "SYMBOL_TRADE_MODE_SHORTONLY", 2))
        close_only = int(getattr(mt5, "SYMBOL_TRADE_MODE_CLOSEONLY", 3))
        full = int(getattr(mt5, "SYMBOL_TRADE_MODE_FULL", 4))
        if trade_mode == disabled:
            raise GatewayError("MT5_SYMBOL_TRADING_DISABLED")
        if not for_close and trade_mode == close_only:
            raise GatewayError("MT5_SYMBOL_CLOSE_ONLY")
        if not for_close:
            side_u = "" if side is None else str(side).upper()
            if side_u == "BUY" and trade_mode == short_only:
                raise GatewayError("MT5_SYMBOL_SHORT_ONLY")
            if side_u == "SELL" and trade_mode == long_only:
                raise GatewayError("MT5_SYMBOL_LONG_ONLY")
            if trade_mode not in {full, long_only, short_only}:
                raise GatewayError(f"MT5_SYMBOL_TRADE_MODE_UNSUPPORTED:{trade_mode}")

            order_mode = int(getattr(info, "order_mode", 0))
            market_flag = int(getattr(mt5, "SYMBOL_ORDER_MARKET", 1))
            sl_flag = int(getattr(mt5, "SYMBOL_ORDER_SL", 16))
            tp_flag = int(getattr(mt5, "SYMBOL_ORDER_TP", 32))
            if (order_mode & market_flag) != market_flag:
                raise GatewayError("MT5_MARKET_ORDERS_NOT_ALLOWED")
            if (order_mode & sl_flag) != sl_flag:
                raise GatewayError("MT5_STOP_LOSS_NOT_ALLOWED")
            if (order_mode & tp_flag) != tp_flag:
                raise GatewayError("MT5_TAKE_PROFIT_NOT_ALLOWED")

    def account_snapshot(self) -> AccountSnapshot:
        a = self._account_info_checked()
        equity = float(a.equity)
        balance = float(a.balance)
        margin_free = float(a.margin_free)
        if not all(math.isfinite(v) for v in (equity, balance, margin_free)):
            raise GatewayError("INVALID_ACCOUNT_NUMERIC_STATE")
        return AccountSnapshot(int(a.login), str(a.server), str(a.currency), equity, balance, margin_free)

    def symbol_snapshot(self) -> SymbolSnapshot:
        mt5 = self._require()
        self._account_info_checked()
        info = self._symbol_info_checked()
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            raise GatewayError("MT5_TICK_UNAVAILABLE")
        tick_ts = float(getattr(tick, "time_msc", 0) or 0) / 1000.0
        if tick_ts <= 0:
            tick_ts = float(tick.time)
        now = datetime.now(timezone.utc).timestamp()
        age = now - tick_ts
        bid, ask = float(tick.bid), float(tick.ask)
        volume_min, volume_step, volume_max, point = float(info.volume_min), float(info.volume_step), float(info.volume_max), float(info.point)
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
        return SymbolSnapshot(SYMBOL, bid, ask, tick_ts, age, volume_min, volume_step, volume_max, point, int(info.trade_stops_level))

    def exposure_snapshot(self) -> ExposureSnapshot:
        self._account_info_checked()
        positions = self._positions()
        orders = self._orders()
        position_lot = sum(float(p.volume) for p in positions)
        pending_lot = sum(float(o.volume_current) for o in orders)
        if not math.isfinite(position_lot) or not math.isfinite(pending_lot) or position_lot < 0 or pending_lot < 0:
            raise GatewayError("INVALID_BROKER_EXPOSURE_STATE")
        return ExposureSnapshot(len(positions), len(orders), position_lot, pending_lot)

    @staticmethod
    def _lot_on_step(lot: float, minimum: float, step: float) -> bool:
        if step <= 0:
            return False
        units = (lot - minimum) / step
        return math.isfinite(units) and abs(units - round(units)) <= 1e-9

    def validate_broker_geometry(self, intent: OrderIntent, symbol: SymbolSnapshot, entry_price: float) -> None:
        lot, stop = float(intent.lot), float(intent.stop_price)
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

    def _commission_for_lot(self, lot: float) -> float:
        commission = COMMISSION_RT_SGD_PER_001_LOT * (float(lot) / 0.01)
        if not math.isfinite(commission) or commission < 0:
            raise GatewayError("INVALID_COMMISSION_PROJECTION")
        return commission

    def _calc_stop_loss(self, side: str, lot: float, entry_price: float, stop_price: float, *, commission_fraction: float = 1.0) -> float:
        mt5 = self._require()
        side_u = side.upper()
        order_type = mt5.ORDER_TYPE_BUY if side_u == "BUY" else mt5.ORDER_TYPE_SELL if side_u == "SELL" else None
        if order_type is None:
            raise GatewayError("UNSUPPORTED_SIDE")
        fraction = float(commission_fraction)
        if not math.isfinite(fraction) or fraction < 0 or fraction > 1:
            raise GatewayError("INVALID_COMMISSION_FRACTION")
        pnl = mt5.order_calc_profit(order_type, SYMBOL, float(lot), float(entry_price), float(stop_price))
        if pnl is None:
            raise GatewayError(f"ORDER_CALC_PROFIT_FAILED:{mt5.last_error()}")
        pnl = float(pnl)
        if not math.isfinite(pnl) or pnl >= 0:
            raise GatewayError(f"INVALID_PROJECTED_STOP_PNL:{pnl}")
        projected = (-pnl) + self._commission_for_lot(lot) * fraction
        if not math.isfinite(projected) or projected <= 0:
            raise GatewayError(f"INVALID_PROJECTED_STOP_WITH_COMMISSION:{projected}")
        return projected

    def projected_stop_loss_sgd(self, intent: OrderIntent, entry_price: float) -> float:
        info = self._symbol_info_checked()
        point = float(info.point)
        side = intent.side.upper()
        worst_entry = float(entry_price) + ORDER_DEVIATION_POINTS * point if side == "BUY" else float(entry_price) - ORDER_DEVIATION_POINTS * point
        if worst_entry <= 0 or not math.isfinite(worst_entry):
            raise GatewayError("INVALID_WORST_CASE_ENTRY")
        return self._calc_stop_loss(side, intent.lot, worst_entry, intent.stop_price)

    def position_stop_loss_sgd(self, position: OwnedPositionSnapshot) -> float:
        if position.sl <= 0:
            raise GatewayError("OWNED_POSITION_MISSING_STOP_LOSS")
        return self._calc_stop_loss(position.side, position.volume, position.price_open, position.sl)

    def position_remaining_stop_loss_sgd(self, position: OwnedPositionSnapshot) -> float:
        if position.sl <= 0:
            raise GatewayError("OWNED_POSITION_MISSING_STOP_LOSS")
        snap = self.symbol_snapshot()
        side = position.side.upper()
        current_exit = snap.bid if side == "BUY" else snap.ask if side == "SELL" else None
        if current_exit is None:
            raise GatewayError("OWNED_POSITION_SIDE_INVALID")
        if side == "BUY" and position.sl >= current_exit:
            raise GatewayError("OWNED_POSITION_STOP_ALREADY_AT_OR_THROUGH_MARKET")
        if side == "SELL" and position.sl <= current_exit:
            raise GatewayError("OWNED_POSITION_STOP_ALREADY_AT_OR_THROUGH_MARKET")
        return self._calc_stop_loss(side, position.volume, current_exit, position.sl, commission_fraction=0.5)

    def _select_filling_mode(self) -> int:
        mt5 = self._require()
        info = self._symbol_info_checked()
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

    def _comment(self, client_intent_id: str) -> str:
        return (COMMENT_PREFIX + client_intent_id)[:31]

    def build_market_request(self, intent: OrderIntent, entry_price: float) -> Dict:
        mt5 = self._require()
        side = intent.side.upper()
        order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL if side == "SELL" else None
        if order_type is None:
            raise GatewayError("UNSUPPORTED_SIDE")
        return {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": SYMBOL,
            "volume": float(intent.lot),
            "type": order_type,
            "price": float(entry_price),
            "sl": float(intent.stop_price),
            "tp": float(intent.take_profit_price or 0.0),
            "deviation": ORDER_DEVIATION_POINTS,
            "magic": MAGIC,
            "comment": self._comment(intent.client_intent_id),
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._select_filling_mode(),
        }

    def order_check(self, request: Dict):
        mt5 = self._require()
        request_type = int(request.get("type", -1))
        if request_type == int(mt5.ORDER_TYPE_BUY):
            side = "BUY"
        elif request_type == int(mt5.ORDER_TYPE_SELL):
            side = "SELL"
        else:
            raise GatewayError("ORDER_CHECK_REQUEST_TYPE_INVALID")
        self.assert_trading_permissions(side)
        check = mt5.order_check(request)
        if check is None:
            raise GatewayError(f"ORDER_CHECK_NONE:{mt5.last_error()}")
        if int(check.retcode) != 0:
            raise GatewayError(f"ORDER_CHECK_REJECTED:{check.retcode}:{check.comment}")
        return check

    def order_send_state(self, result) -> str:
        mt5 = self._require()
        retcode = int(getattr(result, "retcode", -1))
        if retcode == int(mt5.TRADE_RETCODE_DONE):
            return "DONE"
        if retcode == int(mt5.TRADE_RETCODE_PLACED):
            return "PLACED"
        if retcode == int(mt5.TRADE_RETCODE_DONE_PARTIAL):
            return "DONE_PARTIAL"
        return "UNACCEPTED"

    def order_send(self, request: Dict):
        mt5 = self._require()
        request_type = int(request.get("type", -1))
        if request_type == int(mt5.ORDER_TYPE_BUY):
            side = "BUY"
        elif request_type == int(mt5.ORDER_TYPE_SELL):
            side = "SELL"
        else:
            raise GatewayError("ORDER_SEND_REQUEST_TYPE_INVALID")
        self.assert_trading_permissions(side)
        result = mt5.order_send(request)
        if result is None:
            raise GatewayError(f"ORDER_SEND_NONE:{mt5.last_error()}")
        state = self.order_send_state(result)
        if state == "UNACCEPTED":
            raise GatewayError(f"ORDER_SEND_REJECTED:{result.retcode}:{result.comment}")
        return result

    def owned_positions(self, client_intent_id: str) -> List[OwnedPositionSnapshot]:
        self._account_info_checked()
        needle = self._comment(client_intent_id)
        out: List[OwnedPositionSnapshot] = []
        mt5 = self._require()
        for p in self._positions():
            if int(getattr(p, "magic", 0)) != MAGIC or str(getattr(p, "comment", "")) != needle:
                continue
            ptype = int(getattr(p, "type", -1))
            if ptype == int(mt5.POSITION_TYPE_BUY):
                side = "BUY"
            elif ptype == int(mt5.POSITION_TYPE_SELL):
                side = "SELL"
            else:
                raise GatewayError(f"OWNED_POSITION_TYPE_INVALID:{ptype}")
            values = [float(p.volume), float(p.price_open), float(p.sl), float(p.tp)]
            if not all(math.isfinite(v) for v in values):
                raise GatewayError("OWNED_POSITION_NUMERIC_STATE_INVALID")
            if values[0] <= 0 or values[1] <= 0:
                raise GatewayError("OWNED_POSITION_VOLUME_OR_PRICE_INVALID")
            out.append(OwnedPositionSnapshot(int(p.ticket), str(p.symbol), side, values[0], values[1], values[2], values[3], int(p.magic), str(getattr(p, "comment", ""))))
        return out

    def owned_orders(self, client_intent_id: str) -> List:
        self._account_info_checked()
        needle = self._comment(client_intent_id)
        return [o for o in self._orders() if int(getattr(o, "magic", 0)) == MAGIC and str(getattr(o, "comment", "")) == needle]

    def owned_position(self, client_intent_id: str) -> Optional[OwnedPositionSnapshot]:
        rows = self.owned_positions(client_intent_id)
        if len(rows) > 1:
            raise GatewayError("MULTIPLE_OWNED_POSITIONS_FOR_ONE_INTENT")
        return rows[0] if rows else None

    def _emergency_close_price(self, position_side: str) -> float:
        mt5 = self._require()
        self._account_info_checked()
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            raise GatewayError("EMERGENCY_TICK_UNAVAILABLE")
        bid, ask = float(tick.bid), float(tick.ask)
        if not math.isfinite(bid) or not math.isfinite(ask) or bid <= 0 or ask <= 0 or ask < bid:
            raise GatewayError("EMERGENCY_MARKET_QUOTE_INVALID")
        side = position_side.upper()
        if side == "BUY":
            return bid
        if side == "SELL":
            return ask
        raise GatewayError("EMERGENCY_POSITION_SIDE_INVALID")

    def emergency_flatten_owned_intent(self, client_intent_id: str) -> Dict:
        """Best-effort containment for this runtime's own intent only.

        Normal entry spread/tick-age gates are deliberately not reused here: an
        unsafe owned exposure must not remain open merely because the market is
        currently too wide for a new entry. Broker/account identity and quote
        sanity are still enforced, and any residual exposure is reported.
        """
        mt5 = self._require()
        self.assert_trading_permissions(for_close=True)
        cancelled, closed = [], []
        for order in self.owned_orders(client_intent_id):
            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": int(order.ticket),
                "symbol": SYMBOL,
                "magic": MAGIC,
                "comment": "R7R1:EMERGENCY_CANCEL"[:31],
            }
            result = mt5.order_send(request)
            if result is None or int(result.retcode) != int(mt5.TRADE_RETCODE_DONE):
                raise GatewayError(f"EMERGENCY_CANCEL_FAILED:{getattr(result, 'retcode', None)}:{getattr(result, 'comment', '')}")
            cancelled.append(int(order.ticket))

        for position in self.owned_positions(client_intent_id):
            if position.side == "BUY":
                order_type = mt5.ORDER_TYPE_SELL
            else:
                order_type = mt5.ORDER_TYPE_BUY
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": int(position.ticket),
                "symbol": SYMBOL,
                "volume": float(position.volume),
                "type": order_type,
                "price": float(self._emergency_close_price(position.side)),
                "deviation": EMERGENCY_CLOSE_DEVIATION_POINTS,
                "magic": MAGIC,
                "comment": "R7R1:EMERGENCY_FLAT"[:31],
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": self._select_filling_mode(),
            }
            result = mt5.order_send(request)
            if result is None or int(result.retcode) not in {int(mt5.TRADE_RETCODE_DONE), int(mt5.TRADE_RETCODE_DONE_PARTIAL)}:
                raise GatewayError(f"EMERGENCY_CLOSE_FAILED:{getattr(result, 'retcode', None)}:{getattr(result, 'comment', '')}")
            closed.append(int(position.ticket))

        remaining_positions = self.owned_positions(client_intent_id)
        remaining_orders = self.owned_orders(client_intent_id)
        return {
            "ok": not remaining_positions and not remaining_orders,
            "cancelled_orders": cancelled,
            "close_attempted_positions": closed,
            "remaining_owned_positions": [p.ticket for p in remaining_positions],
            "remaining_owned_orders": [int(o.ticket) for o in remaining_orders],
        }

    def find_intent_at_broker(self, client_intent_id: str) -> BrokerMatch:
        self._account_info_checked()
        needle = self._comment(client_intent_id)
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
