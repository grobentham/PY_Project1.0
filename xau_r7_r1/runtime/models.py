from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class AccountSnapshot:
    login: int
    server: str
    currency: str
    equity_sgd: float
    balance_sgd: float
    margin_free_sgd: float


@dataclass(frozen=True)
class SymbolSnapshot:
    symbol: str
    bid: float
    ask: float
    tick_time_epoch: float
    tick_age_seconds: float
    volume_min: float
    volume_step: float
    volume_max: float
    point: float
    trade_stops_level_points: int

    @property
    def spread_usd(self) -> float:
        return self.ask - self.bid


@dataclass(frozen=True)
class ExposureSnapshot:
    position_count: int
    pending_order_count: int
    total_position_lot: float
    total_pending_lot: float

    @property
    def total_count(self) -> int:
        return self.position_count + self.pending_order_count

    @property
    def total_lot(self) -> float:
        return self.total_position_lot + self.total_pending_lot


@dataclass(frozen=True)
class OwnedPositionSnapshot:
    ticket: int
    symbol: str
    side: str
    volume: float
    price_open: float
    sl: float
    tp: float
    magic: int
    comment: str


@dataclass(frozen=True)
class OrderIntent:
    client_intent_id: str
    side: str
    lot: float
    stop_price: float
    take_profit_price: Optional[float]
    source: str
    frozen_atr_usd: Optional[float] = None
    frozen_stop_atr: Optional[float] = None
    frozen_target_atr: Optional[float] = None
    decision_fingerprint: Optional[str] = None
    execution_authority: Optional[str] = None

    def canonical_payload(self) -> Dict[str, Any]:
        frozen = (self.frozen_atr_usd, self.frozen_stop_atr, self.frozen_target_atr)
        if all(v is not None for v in frozen):
            return {
                "client_intent_id": self.client_intent_id,
                "side": self.side,
                "lot": self.lot,
                "source": self.source,
                "geometry_mode": "FROZEN_ATR",
                "frozen_atr_usd": self.frozen_atr_usd,
                "frozen_stop_atr": self.frozen_stop_atr,
                "frozen_target_atr": self.frozen_target_atr,
                "decision_fingerprint": self.decision_fingerprint,
                "execution_authority": self.execution_authority,
            }
        return asdict(self)


@dataclass(frozen=True)
class DerivedRisk:
    entry_price: float
    projected_stop_loss_sgd: float
    projected_stop_risk_pct: float
    projected_equity_after_stop_sgd: float


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str
    risk: DerivedRisk


@dataclass(frozen=True)
class BrokerMatch:
    found: bool
    kind: Optional[str] = None
    ticket: Optional[int] = None
    state: Optional[str] = None
