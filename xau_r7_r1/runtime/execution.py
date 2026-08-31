from __future__ import annotations

import math
import re
from dataclasses import asdict, replace
from typing import Any, Dict, List

from .audit_store import AuditStore
from .constants import MAX_CANONICAL_LOT, R6_EXECUTION_AUTHORITY
from .models import BrokerMatch, OrderIntent
from .r6_decision_adapter import round_price_to_point
from .risk import RiskGovernor

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
_SOURCE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ExecutionError(RuntimeError):
    pass


class ExecutionEngine:
    def __init__(self, store: AuditStore, gateway, *, execution_enabled: bool = False):
        self.store = store
        self.gateway = gateway
        self.execution_enabled = bool(execution_enabled)
        self.risk = RiskGovernor()

    @staticmethod
    def validate_intent_shape(intent: OrderIntent) -> None:
        if not _ID_RE.fullmatch(intent.client_intent_id):
            raise ExecutionError("INVALID_CLIENT_INTENT_ID")
        if intent.side.upper() not in {"BUY", "SELL"}:
            raise ExecutionError("UNSUPPORTED_SIDE")
        if not isinstance(intent.source, str) or not _SOURCE_RE.fullmatch(intent.source):
            raise ExecutionError("INVALID_SOURCE")
        numeric = [float(intent.lot), float(intent.stop_price)]
        if intent.take_profit_price is not None:
            numeric.append(float(intent.take_profit_price))
        if not all(math.isfinite(v) for v in numeric):
            raise ExecutionError("NONFINITE_INTENT_GEOMETRY")
        if float(intent.lot) <= 0:
            raise ExecutionError("NON_POSITIVE_LOT")
        if float(intent.stop_price) <= 0:
            raise ExecutionError("NON_POSITIVE_STOP_PRICE")
        if intent.take_profit_price is not None and float(intent.take_profit_price) <= 0:
            raise ExecutionError("NON_POSITIVE_TARGET_PRICE")

        frozen = (intent.frozen_atr_usd, intent.frozen_stop_atr, intent.frozen_target_atr)
        has_frozen = [v is not None for v in frozen]
        if any(has_frozen) and not all(has_frozen):
            raise ExecutionError("PARTIAL_FROZEN_ATR_GEOMETRY")
        if all(has_frozen):
            frozen_values = [float(v) for v in frozen]
            if not all(math.isfinite(v) and v > 0 for v in frozen_values):
                raise ExecutionError("INVALID_FROZEN_ATR_GEOMETRY")
            if not isinstance(intent.decision_fingerprint, str) or not _SHA256_RE.fullmatch(intent.decision_fingerprint):
                raise ExecutionError("INVALID_DECISION_FINGERPRINT")
            if intent.execution_authority != R6_EXECUTION_AUTHORITY:
                raise ExecutionError("FROZEN_GEOMETRY_REQUIRES_R6_EXECUTION_AUTHORITY")
        else:
            if intent.decision_fingerprint is not None:
                raise ExecutionError("FINGERPRINT_WITHOUT_FROZEN_GEOMETRY")
            if intent.execution_authority is not None:
                raise ExecutionError("EXECUTION_AUTHORITY_WITHOUT_FROZEN_GEOMETRY")

    @staticmethod
    def _materialize_frozen_geometry(intent: OrderIntent, symbol, entry: float) -> OrderIntent:
        if intent.frozen_atr_usd is None:
            return intent
        atr = float(intent.frozen_atr_usd)
        stop_atr = float(intent.frozen_stop_atr)
        target_atr = float(intent.frozen_target_atr)
        if intent.side.upper() == "BUY":
            stop = entry - stop_atr * atr
            target = entry + target_atr * atr
        else:
            stop = entry + stop_atr * atr
            target = entry - target_atr * atr
        stop = round_price_to_point(stop, float(symbol.point))
        target = round_price_to_point(target, float(symbol.point))
        return replace(intent, stop_price=stop, take_profit_price=target)

    def _broker_preflight(self, intent: OrderIntent) -> Dict[str, Any]:
        account = self.gateway.account_snapshot()
        symbol = self.gateway.symbol_snapshot()
        exposure = self.gateway.exposure_snapshot()
        entry = self.gateway.current_market_entry(intent.side, symbol)
        effective_intent = self._materialize_frozen_geometry(intent, symbol, entry)
        self.gateway.validate_broker_geometry(effective_intent, symbol, entry)
        stop_loss_sgd = self.gateway.projected_stop_loss_sgd(effective_intent, entry)
        decision = self.risk.evaluate(
            account=account,
            exposure=exposure,
            intent=effective_intent,
            entry_price=entry,
            projected_stop_loss_sgd=stop_loss_sgd,
        )
        request = self.gateway.build_market_request(effective_intent, entry)
        return {
            "account": asdict(account),
            "symbol": asdict(symbol),
            "exposure": asdict(exposure),
            "decision": asdict(decision),
            "request": request,
            "effective_geometry": {
                "stop_price": effective_intent.stop_price,
                "take_profit_price": effective_intent.take_profit_price,
                "frozen_atr_usd": effective_intent.frozen_atr_usd,
                "frozen_stop_atr": effective_intent.frozen_stop_atr,
                "frozen_target_atr": effective_intent.frozen_target_atr,
            },
        }

    def _post_send_exposure_ok(self, match: BrokerMatch) -> Dict[str, Any]:
        exposure = self.gateway.exposure_snapshot()
        detail = asdict(exposure)
        if exposure.total_lot > MAX_CANONICAL_LOT + 1e-12:
            return {"ok": False, "reason": "POST_SEND_MAX_EXPOSURE_BREACH", "exposure": detail}
        if match.kind in {"POSITION", "ORDER"}:
            if exposure.total_count != 1:
                return {"ok": False, "reason": "POST_SEND_EXPOSURE_COUNT_MISMATCH", "exposure": detail}
        elif match.kind == "DEAL":
            if exposure.total_count != 0:
                return {"ok": False, "reason": "POST_SEND_UNEXPECTED_XAU_EXPOSURE", "exposure": detail}
        else:
            return {"ok": False, "reason": "POST_SEND_UNKNOWN_BROKER_MATCH_KIND", "exposure": detail}
        return {"ok": True, "exposure": detail}

    def _acknowledge_or_manual(self, intent_id: str, match: BrokerMatch, *, base_detail: Dict[str, Any]) -> Dict[str, Any]:
        try:
            post = self._post_send_exposure_ok(match)
        except Exception as exc:
            self.store.transition(
                intent_id, "MANUAL_REVIEW_NO_RESUBMIT", broker_ticket=match.ticket,
                error=f"POST_SEND_EXPOSURE_QUERY_FAILED:{exc}",
                detail={**base_detail, "broker_match": asdict(match), "automatic_resubmit": False},
            )
            return {"ok": False, "state": "MANUAL_REVIEW_NO_RESUBMIT", "reason": f"POST_SEND_EXPOSURE_QUERY_FAILED:{exc}", "broker_match": asdict(match)}
        detail = dict(base_detail)
        detail.update({"broker_kind": match.kind, "broker_state": match.state, "post_send": post})
        if not post["ok"]:
            self.store.transition(intent_id, "MANUAL_REVIEW_NO_RESUBMIT", broker_ticket=match.ticket, error=post["reason"], detail=detail)
            return {"ok": False, "state": "MANUAL_REVIEW_NO_RESUBMIT", "reason": post["reason"], "broker_match": asdict(match), "post_send": post}
        self.store.transition(intent_id, "ACKNOWLEDGED", broker_ticket=match.ticket, detail=detail)
        return {"ok": True, "state": "ACKNOWLEDGED", "broker_match": asdict(match), "post_send": post}

    def _find_broker_match_fail_closed(self, intent_id: str, *, after_send: bool) -> BrokerMatch:
        try:
            return self.gateway.find_intent_at_broker(intent_id)
        except Exception as exc:
            if after_send:
                self.store.transition(intent_id, "MANUAL_REVIEW_NO_RESUBMIT", error=f"BROKER_RECONCILIATION_FAILED:{exc}", detail={"automatic_resubmit": False})
                raise ExecutionError(f"BROKER_RECONCILIATION_FAILED_NO_RESUBMIT:{exc}") from exc
            self.store.transition(intent_id, "FAILED_SAFE", error=f"BROKER_DUPLICATE_CHECK_FAILED:{exc}")
            raise ExecutionError(f"BROKER_DUPLICATE_CHECK_FAILED:{exc}") from exc

    def submit(self, intent: OrderIntent) -> Dict[str, Any]:
        self.validate_intent_shape(intent)
        if self.execution_enabled and intent.execution_authority != R6_EXECUTION_AUTHORITY:
            self.store.append_event("EXECUTION_AUTHORITY_REJECTED", {
                "client_intent_id": intent.client_intent_id,
                "source": intent.source,
                "execution_authority": intent.execution_authority,
            })
            return {"ok": False, "state": "BLOCKED", "reason": "FROZEN_R6_EXECUTION_AUTHORITY_REQUIRED"}

        payload = intent.canonical_payload()
        created = self.store.reserve_intent(intent.client_intent_id, payload)
        if not created:
            existing = self.store.get_intent(intent.client_intent_id)
            self.store.append_event("DUPLICATE_SUBMIT_SUPPRESSED", {"client_intent_id": intent.client_intent_id, "state": existing["state"]})
            return {"ok": False, "duplicate_suppressed": True, "intent": existing}

        try:
            preexisting = self._find_broker_match_fail_closed(intent.client_intent_id, after_send=False)
        except ExecutionError as exc:
            return {"ok": False, "state": "FAILED_SAFE", "reason": str(exc)}
        if preexisting.found:
            return self._acknowledge_or_manual(intent.client_intent_id, preexisting, base_detail={"broker_duplicate_preexisting": True, "send_attempted": False})

        try:
            first = self._broker_preflight(intent)
        except Exception as exc:
            self.store.transition(intent.client_intent_id, "BLOCKED", error=str(exc))
            return {"ok": False, "state": "BLOCKED", "reason": str(exc)}

        decision = first["decision"]
        if not decision["allowed"]:
            self.store.transition(intent.client_intent_id, "BLOCKED", error=decision["reason"], detail={"risk": decision["risk"], "geometry": first["effective_geometry"]})
            return {"ok": False, "state": "BLOCKED", "reason": decision["reason"], "risk": decision["risk"]}
        try:
            self.gateway.order_check(first["request"])
        except Exception as exc:
            self.store.transition(intent.client_intent_id, "BLOCKED", error=str(exc))
            return {"ok": False, "state": "BLOCKED", "reason": str(exc)}

        self.store.transition(intent.client_intent_id, "PREFLIGHT_OK", detail={"risk": decision["risk"], "entry_price": first["request"]["price"], "geometry": first["effective_geometry"]})
        if not self.execution_enabled:
            self.store.transition(intent.client_intent_id, "DRY_RUN_COMPLETE", detail={"send_attempted": False})
            return {"ok": True, "state": "DRY_RUN_COMPLETE", "send_attempted": False, "risk": decision["risk"], "geometry": first["effective_geometry"]}

        try:
            second = self._broker_preflight(intent)
            second_decision = second["decision"]
            if not second_decision["allowed"]:
                self.store.transition(intent.client_intent_id, "ABANDONED_BEFORE_SEND", error=second_decision["reason"], detail={"risk": second_decision["risk"], "geometry": second["effective_geometry"]})
                return {"ok": False, "state": "ABANDONED_BEFORE_SEND", "reason": second_decision["reason"]}
            self.gateway.order_check(second["request"])
        except Exception as exc:
            self.store.transition(intent.client_intent_id, "ABANDONED_BEFORE_SEND", error=str(exc))
            return {"ok": False, "state": "ABANDONED_BEFORE_SEND", "reason": str(exc)}

        self.store.transition(intent.client_intent_id, "SUBMITTING", detail={"entry_price": second["request"]["price"], "geometry": second["effective_geometry"]})
        try:
            result = self.gateway.order_send(second["request"])
            ticket = int(getattr(result, "order", 0) or getattr(result, "deal", 0) or 0) or None
            self.store.transition(intent.client_intent_id, "SUBMITTED", broker_ticket=ticket)
        except Exception as send_exc:
            try:
                match = self._find_broker_match_fail_closed(intent.client_intent_id, after_send=True)
            except ExecutionError as reconcile_exc:
                return {"ok": False, "state": "MANUAL_REVIEW_NO_RESUBMIT", "reason": str(reconcile_exc), "send_error": str(send_exc)}
            if match.found:
                return self._acknowledge_or_manual(intent.client_intent_id, match, base_detail={"recovered_after_send_exception": True, "send_error": str(send_exc)})
            self.store.transition(intent.client_intent_id, "MANUAL_REVIEW_NO_RESUBMIT", error=str(send_exc), detail={"automatic_resubmit": False})
            return {"ok": False, "state": "MANUAL_REVIEW_NO_RESUBMIT", "reason": str(send_exc)}

        try:
            match = self._find_broker_match_fail_closed(intent.client_intent_id, after_send=True)
        except ExecutionError as exc:
            return {"ok": False, "state": "MANUAL_REVIEW_NO_RESUBMIT", "reason": str(exc)}
        if match.found:
            return self._acknowledge_or_manual(intent.client_intent_id, match, base_detail={"order_send_returned_success": True})
        self.store.transition(intent.client_intent_id, "MANUAL_REVIEW_NO_RESUBMIT", detail={"order_send_returned_success": True, "broker_match_found": False, "automatic_resubmit": False})
        return {"ok": False, "state": "MANUAL_REVIEW_NO_RESUBMIT", "reason": "BROKER_ACK_NOT_RECONCILED"}

    def recover_inflight(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for row in self.store.inflight_intents():
            intent_id = row["client_intent_id"]
            state = row["state"]
            if state in {"RESERVED", "PREFLIGHT_OK"}:
                self.store.transition(intent_id, "ABANDONED_BEFORE_SEND", detail={"restart_recovery": True, "send_was_not_started": True})
                results.append({"client_intent_id": intent_id, "state": "ABANDONED_BEFORE_SEND"})
                continue
            if state in {"SUBMITTING", "SUBMITTED"}:
                try:
                    match = self._find_broker_match_fail_closed(intent_id, after_send=True)
                except ExecutionError as exc:
                    results.append({"client_intent_id": intent_id, "state": "MANUAL_REVIEW_NO_RESUBMIT", "reason": str(exc)})
                    continue
                if match.found:
                    result = self._acknowledge_or_manual(intent_id, match, base_detail={"restart_recovery": True})
                    result["client_intent_id"] = intent_id
                    results.append(result)
                else:
                    self.store.transition(intent_id, "MANUAL_REVIEW_NO_RESUBMIT", detail={"restart_recovery": True, "automatic_resubmit": False})
                    results.append({"client_intent_id": intent_id, "state": "MANUAL_REVIEW_NO_RESUBMIT"})
        return results
