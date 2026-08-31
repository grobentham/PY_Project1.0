from __future__ import annotations

import math

from .constants import (
    CONSTITUTIONAL_PROJECTED_STOP_RISK_PCT,
    MAX_CANONICAL_LOT,
    MAX_SIMULTANEOUS_SYMBOL_EXPOSURES,
    OPERATING_PROJECTED_STOP_RISK_PCT,
    PROJECTED_EQUITY_FLOOR_SGD,
    RETIRED_SOURCE,
)
from .models import AccountSnapshot, DerivedRisk, ExposureSnapshot, GateDecision, OrderIntent, OwnedPositionSnapshot


class RiskGovernor:
    @staticmethod
    def _risk(account: AccountSnapshot, *, entry_price: float, loss: float) -> DerivedRisk:
        equity = float(account.equity_sgd)
        pct = (float(loss) / equity * 100.0) if equity > 0 else math.inf
        return DerivedRisk(float(entry_price), float(loss), pct, equity - float(loss))

    @staticmethod
    def _limit_decision(risk: DerivedRisk, *, lot: float) -> GateDecision:
        if not math.isfinite(risk.projected_stop_loss_sgd) or risk.projected_stop_loss_sgd <= 0:
            return GateDecision(False, "INVALID_PROJECTED_STOP_LOSS", risk)
        if lot <= 0:
            return GateDecision(False, "NON_POSITIVE_LOT", risk)
        if lot > MAX_CANONICAL_LOT + 1e-12:
            return GateDecision(False, "MAX_CANONICAL_EXPOSURE_EXCEEDED", risk)
        if risk.projected_equity_after_stop_sgd < PROJECTED_EQUITY_FLOOR_SGD - 1e-12:
            return GateDecision(False, "PROJECTED_EQUITY_FLOOR_BREACH", risk)
        if risk.projected_stop_risk_pct > CONSTITUTIONAL_PROJECTED_STOP_RISK_PCT + 1e-12:
            return GateDecision(False, "CONSTITUTIONAL_RISK_CEILING_BREACH", risk)
        if risk.projected_stop_risk_pct > OPERATING_PROJECTED_STOP_RISK_PCT + 1e-12:
            return GateDecision(False, "OPERATING_RISK_CAP_BREACH", risk)
        return GateDecision(True, "ALLOW", risk)

    def evaluate(
        self,
        *,
        account: AccountSnapshot,
        exposure: ExposureSnapshot,
        intent: OrderIntent,
        entry_price: float,
        projected_stop_loss_sgd: float,
    ) -> GateDecision:
        equity = float(account.equity_sgd)
        risk = self._risk(account, entry_price=entry_price, loss=projected_stop_loss_sgd)
        if intent.source == RETIRED_SOURCE:
            return GateDecision(False, "RETIRED_SOURCE_AUX_RF_LTM", risk)
        if equity <= 0:
            return GateDecision(False, "NON_POSITIVE_EQUITY", risk)
        if exposure.total_count >= MAX_SIMULTANEOUS_SYMBOL_EXPOSURES:
            return GateDecision(False, "EXISTING_XAU_EXPOSURE_BLOCK", risk)
        if exposure.total_lot > 1e-12:
            return GateDecision(False, "EXISTING_XAU_VOLUME_BLOCK", risk)
        return self._limit_decision(risk, lot=float(intent.lot))

    def evaluate_filled_position(
        self,
        *,
        account: AccountSnapshot,
        position: OwnedPositionSnapshot,
        projected_stop_loss_sgd: float,
    ) -> GateDecision:
        if float(account.equity_sgd) <= 0:
            risk = self._risk(account, entry_price=position.price_open, loss=projected_stop_loss_sgd)
            return GateDecision(False, "NON_POSITIVE_EQUITY", risk)
        risk = self._risk(account, entry_price=position.price_open, loss=projected_stop_loss_sgd)
        return self._limit_decision(risk, lot=float(position.volume))
