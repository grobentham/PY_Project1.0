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
from .models import AccountSnapshot, DerivedRisk, ExposureSnapshot, GateDecision, OrderIntent


class RiskGovernor:
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
        loss = float(projected_stop_loss_sgd)
        lot = float(intent.lot)
        pct = (loss / equity * 100.0) if equity > 0 else math.inf
        projected_equity = equity - loss
        risk = DerivedRisk(
            entry_price=float(entry_price),
            projected_stop_loss_sgd=loss,
            projected_stop_risk_pct=pct,
            projected_equity_after_stop_sgd=projected_equity,
        )

        if intent.source == RETIRED_SOURCE:
            return GateDecision(False, "RETIRED_SOURCE_AUX_RF_LTM", risk)
        if equity <= 0:
            return GateDecision(False, "NON_POSITIVE_EQUITY", risk)
        if not math.isfinite(loss) or loss <= 0:
            return GateDecision(False, "INVALID_PROJECTED_STOP_LOSS", risk)
        if exposure.total_count >= MAX_SIMULTANEOUS_SYMBOL_EXPOSURES:
            return GateDecision(False, "EXISTING_XAU_EXPOSURE_BLOCK", risk)
        if exposure.total_lot > 1e-12:
            return GateDecision(False, "EXISTING_XAU_VOLUME_BLOCK", risk)
        if lot <= 0:
            return GateDecision(False, "NON_POSITIVE_LOT", risk)
        if lot > MAX_CANONICAL_LOT + 1e-12:
            return GateDecision(False, "MAX_CANONICAL_EXPOSURE_EXCEEDED", risk)
        if projected_equity < PROJECTED_EQUITY_FLOOR_SGD - 1e-12:
            return GateDecision(False, "PROJECTED_EQUITY_FLOOR_BREACH", risk)
        if pct > CONSTITUTIONAL_PROJECTED_STOP_RISK_PCT + 1e-12:
            return GateDecision(False, "CONSTITUTIONAL_RISK_CEILING_BREACH", risk)
        if pct > OPERATING_PROJECTED_STOP_RISK_PCT + 1e-12:
            return GateDecision(False, "OPERATING_RISK_CAP_BREACH", risk)
        return GateDecision(True, "ALLOW", risk)
